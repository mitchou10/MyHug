"""What uploads and downloads share, with no network in it: files, fingerprints, progress, where the state is kept."""

import hashlib
import json
import mimetypes
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

CHUNK = 1024 * 1024
PARALLEL = 3
ATTEMPTS = 3


@dataclass
class Progress:
    """Bytes done of the bytes to do, for what is being sent or received (`path`: the file, when it is one)."""

    done: int
    total: int
    path: str | None = None


ProgressCallback = Callable[[Progress], None]


@dataclass
class LocalFile:
    """A file to send: where it is, the path it will have in the version, and its fingerprint once known."""

    source: Path
    path: str
    size: int = 0
    sha256: str | None = None
    content_type: str | None = field(default=None)

    def __post_init__(self) -> None:
        self.size = self.source.stat().st_size
        self.content_type = self.content_type or mimetypes.guess_type(self.path)[0]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def part_size(file_size: int, part_bytes: int, number: int) -> int:
    """The size of part `number` (from 1): all are `part_bytes` long but the last, which is what is left."""
    return max(0, min(part_bytes, file_size - (number - 1) * part_bytes))


def missing_parts(entry: dict, received: dict[int, int]) -> list[int]:
    """The parts of a announced file that are not in the storage with the right size."""
    return [
        n
        for n in range(1, entry["parts_count"] + 1)
        if received.get(n) != part_size(entry["size_bytes"], entry["part_size"], n)
    ]


def read_part(file: LocalFile, entry: dict, number: int) -> bytes:
    """One part of a file, read when it is sent: the memory used is a part, not the file. A file that is not the one
    that was announced (another size now) is refused."""
    if file.source.stat().st_size != entry["size_bytes"]:
        raise FileChangedError(entry["path"])
    with file.source.open("rb") as handle:
        handle.seek((number - 1) * entry["part_size"])
        return handle.read(part_size(entry["size_bytes"], entry["part_size"], number))


class FileChangedError(Exception):
    """Turned into `FileChanged` by the callers (kept apart so this module has no dependency on the clients)."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


# ---- where an unfinished upload is remembered, so that running it again goes on


def state_dir(base: Path | None) -> Path:
    root = base or Path(os.environ.get("MYHUG_CACHE") or Path.home() / ".cache" / "myhug")
    return root / "uploads"


def state_key(start: str, files: list[LocalFile], remove: list[str], message: str) -> str:
    """The same upload is the same key: where it goes, which files (path, size, date) and what is removed."""
    parts = [start, message, *sorted(remove)]
    for f in sorted(files, key=lambda f: f.path):
        parts.append(f"{f.path}:{f.size}:{f.source.stat().st_mtime_ns}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:32]


def load_state(folder: Path, key: str) -> str | None:
    try:
        return json.loads((folder / f"{key}.json").read_text())["upload_id"]
    except (OSError, ValueError, KeyError):
        return None


def save_state(folder: Path, key: str, upload_id: str) -> None:
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    (folder / f"{key}.json").write_text(json.dumps({"upload_id": upload_id}))


def forget_state(folder: Path, key: str) -> None:
    (folder / f"{key}.json").unlink(missing_ok=True)


# ---- the local copy of what was downloaded, by fingerprint: the same file is never fetched twice


class Cache:
    def __init__(self, folder: Path) -> None:
        self._blobs = folder / "blobs"

    def blob(self, sha256: str) -> Path:
        return self._blobs / sha256[:2] / sha256

    def has(self, sha256: str) -> bool:
        return self.blob(sha256).is_file()

    def add(self, source: Path, sha256: str) -> None:
        target = self.blob(sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            link_or_copy(source, target)

    def give(self, sha256: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        link_or_copy(self.blob(sha256), dest)


def link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:  # another disk, or a file system without links
        shutil.copy2(source, target)


def cache_folder(base: Path | None) -> Path:
    return base or Path(os.environ.get("MYHUG_CACHE") or Path.home() / ".cache" / "myhug")
