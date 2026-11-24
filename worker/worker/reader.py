import hashlib
import tempfile
from typing import Any

from worker import tables
from worker.backend import Backend, FileToRead
from worker.config import settings
from worker.errors import FileMissing, UnreadableFile


def read(backend: Backend, file: FileToRead) -> dict[str, Any]:
    """Downloads a file to the disk as it comes (never whole in memory), computes its fingerprint on the way, then
    counts its rows and finds its columns when it holds some. What it found, as the API wants it."""
    with tempfile.TemporaryFile(dir=settings.WORKER_TEMP_DIR or None) as handle:
        digest, size = hashlib.sha256(), 0
        try:
            for chunk in backend.download(file.url):
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        except FileMissing:
            raise FileMissing(f"{file.path} is missing from the storage") from None
        found: dict[str, Any] = {"id": str(file.id), "size_bytes": size}
        if file.needs_fingerprint:
            found["sha256"] = digest.hexdigest()
        if file.needs_rows:
            handle.flush()
            info = tables.inspect(file.path, handle)
            found["rows"] = info.rows
            found["columns"] = [{"name": column.name, "dtype": column.dtype} for column in info.columns]
        return found


def fingerprint(backend: Backend, file: FileToRead) -> dict[str, Any]:
    """The size and the fingerprint of a file, computed as it comes: it is never kept (a model file can be tens of GiB,
    and nothing is read in it)."""
    digest, size = hashlib.sha256(), 0
    try:
        for chunk in backend.download(file.url):
            digest.update(chunk)
            size += len(chunk)
    except FileMissing:
        raise FileMissing(f"{file.path} is missing from the storage") from None
    return {"id": str(file.id), "size_bytes": size, "sha256": digest.hexdigest()}


__all__ = ["FileMissing", "UnreadableFile", "fingerprint", "read"]
