"""What to do with files, decided without touching the network: which ones, where they go, what a folder changes."""

import fnmatch
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from myhug._transfer import LocalFile, sha256_of

# What a folder does not send by default.
DEFAULT_IGNORE = (".git/*", ".DS_Store", "*/.DS_Store", "__pycache__/*", "*/__pycache__/*", "*.pyc", "*.part")


def remote_path(path: str) -> str:
    """A path as the platform stores it: relative, with `/`, no `..`. Anything else is refused."""
    clean = PurePosixPath(path.replace("\\", "/"))
    if clean.is_absolute() or not clean.parts or ".." in clean.parts or str(clean) == ".":
        raise ValueError(f"{path!r} is not a path inside a version")
    return str(clean)


def inside(folder: Path, path: str) -> Path:
    """Where a remote path goes under `folder`: refused when it would leave it."""
    target = (folder / remote_path(path)).resolve()
    if folder.resolve() not in target.parents:
        raise ValueError(f"{path!r} would leave the folder it is downloaded to")
    return target


def select(files: Sequence[Any], *, split: str | None, path: str | None, known_splits: Sequence[str]) -> list[Any]:
    """The files of a version a call is about: a `path`, or a `split`, or all of them."""
    if path is not None:
        found = [f for f in files if f.path == path]
        if not found:
            raise ValueError(f"No file {path!r} in this version")
        return found
    if split is None:
        return list(files)
    if split not in known_splits:
        raise ValueError(f"No split {split!r}: this dataset has {', '.join(known_splits) or 'none'}")
    return [f for f in files if f.split == split]


def walk(folder: Path, *, ignore: Sequence[str] = DEFAULT_IGNORE, prefix: str = "") -> list[LocalFile]:
    """The files under a folder, with the path each will have (relative to the folder, under `prefix`)."""
    root = folder.resolve()
    if not root.is_dir():
        raise ValueError(f"{folder} is not a folder")
    found: list[LocalFile] = []
    for source in sorted(root.rglob("*")):
        relative = source.relative_to(root).as_posix()
        if not source.is_file() or any(fnmatch.fnmatch(relative, pattern) for pattern in ignore):
            continue
        found.append(
            LocalFile(source, remote_path(f"{prefix.strip('/')}/{relative}" if prefix.strip("/") else relative))
        )
    return found


@dataclass(frozen=True)
class FolderPlan:
    send: list[LocalFile]  # new or changed
    remove: list[str]  # in the version, no longer in the folder (only when asked)
    same: int  # already there, untouched

    @property
    def nothing(self) -> bool:
        return not self.send and not self.remove


def plan_folder(local: Sequence[LocalFile], remote: Sequence[Any], *, delete: bool) -> FolderPlan:
    """What a folder changes in the latest version: a file whose fingerprint is the same is left alone; one whose
    fingerprint the platform does not know yet is sent again (it cannot be told to be the same)."""
    held = {f.path: f.sha256 for f in remote}
    send: list[LocalFile] = []
    same = 0
    for file in local:
        file.sha256 = file.sha256 or sha256_of(file.source)
        if held.get(file.path) == file.sha256:
            same += 1
        else:
            send.append(file)
    kept = {f.path for f in local}
    remove = sorted(path for path in held if path not in kept) if delete else []
    return FolderPlan(send, remove, same)
