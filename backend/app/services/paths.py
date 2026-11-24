import posixpath

from app.services.errors import InvalidFilePath


def clean_path(path: str) -> str:
    """A path inside a dataset: relative, with `/`, nothing like `..`. Raises InvalidFilePath."""
    candidate = path.strip().replace("\\", "/").lstrip("/")
    parts = candidate.split("/")
    if not candidate or len(candidate) > 512 or any(part in ("", ".", "..") or len(part) > 255 for part in parts):
        raise InvalidFilePath
    if any(ord(char) < 32 for char in candidate):
        raise InvalidFilePath
    return posixpath.normpath(candidate)
