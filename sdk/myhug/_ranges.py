"""A file in the storage that is read by ranges, as if it were open on disk.

Parquet is read from its end (the footer says where everything is) and then group by group, so a reader needs
`seek` and `read`, not the whole file. This gives it that over a signed address, with one request for each stretch it
asks (`Range: bytes=a-b`), and nothing kept but the last stretch."""

import io
from collections.abc import Callable

from myhug.errors import ConnectionFailed

BLOCK = 1024 * 1024  # a stretch asked is at least this long: many small reads are one request

# What fetches a stretch: `(start, end)` (end excluded) -> its bytes, and the size of the file if the storage says.
Fetch = Callable[[int, int], tuple[bytes, int | None]]


class RangeFile(io.RawIOBase):
    def __init__(self, fetch: Fetch) -> None:
        super().__init__()
        self._fetch = fetch
        self._position = 0
        self._window_start = 0
        self._window = b""
        _, total = fetch(0, 1)
        if total is None:
            raise ConnectionFailed("The storage did not say how large the file is")
        self.size: int = total

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._position, io.SEEK_END: self.size}[whence]
        self._position = max(0, base + offset)
        return self._position

    def readinto(self, buffer: bytearray | memoryview) -> int:  # ty: ignore[incompatible-method-override]
        wanted = min(len(buffer), max(0, self.size - self._position))
        if wanted == 0:
            return 0
        end = self._position + wanted
        window_end = self._window_start + len(self._window)
        if not (self._window_start <= self._position and end <= window_end):
            start = self._position
            data, _ = self._fetch(start, min(self.size, start + max(wanted, BLOCK)))
            if len(data) < wanted:
                raise ConnectionFailed("The storage gave less than was asked")
            self._window_start, self._window = start, data
        offset = self._position - self._window_start
        buffer[:wanted] = self._window[offset : offset + wanted]
        self._position += wanted
        return wanted


def ranged(answer, start: int, end: int) -> tuple[bytes, int | None]:
    """The bytes of a stretch from the answer of the storage, and the size of the whole file when it says it
    (`Content-Range: bytes 0-0/1234`). A storage that does not do ranges answers the whole file: it is cut here."""
    from myhug.errors import ApiError

    if answer.status_code == 416:
        return b"", None
    if answer.status_code not in (200, 206):
        raise ApiError(answer.status_code, "The storage refused the download")
    total = None
    if answer.status_code == 206:
        _, _, size = answer.headers.get("content-range", "").rpartition("/")
        total = int(size) if size.isdigit() else None
        return answer.content, total
    return answer.content[start:end], len(answer.content)
