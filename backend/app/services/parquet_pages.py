"""Reading pages of rows from a Parquet copy kept in the storage, without bringing the whole file: Parquet is read by
ranges (the footer, then the row groups a page needs), and the storage gives ranges.

pyarrow reads from a file and waits for each answer, while the storage is asked without waiting. So the reading runs
in a thread, and each range it asks for is fetched in the event loop of the request."""

import asyncio
import io
import json
from collections.abc import Callable
from typing import Any

import pyarrow.parquet as pq

from app.services import tables
from app.storage import ObjectStore

BUFFER_BYTES = 1024 * 1024  # one request to the storage serves many small reads of pyarrow


class _StoredRange(io.RawIOBase):
    """A stored object seen as a file, read from a thread by asking the event loop for each range."""

    def __init__(self, store: ObjectStore, key: str, size: int, loop: asyncio.AbstractEventLoop) -> None:
        self._store, self._key, self._size, self._loop = store, key, size, loop
        self._position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._position, io.SEEK_END: self._size}[whence]
        self._position = max(0, base + offset)
        return self._position

    def readinto(self, buffer: Any) -> int:
        wanted = min(len(buffer), max(0, self._size - self._position))
        if wanted == 0:
            return 0
        data = asyncio.run_coroutine_threadsafe(
            self._store.get_range(self._key, self._position, wanted), self._loop
        ).result()
        buffer[: len(data)] = data
        self._position += len(data)
        return len(data)


def _decoded(batch: Any, index: int) -> list[Any]:
    """The values of a column. A column of lists or objects is written as JSON text (the field says so): read back."""
    values = batch.column(index).to_pylist()
    metadata = batch.schema.field(index).metadata or {}
    if metadata.get(b"json") == b"1":
        return [None if value is None else json.loads(value) for value in values]
    return values


def _rows(batch: Any) -> list[list[Any]]:
    columns = [_decoded(batch, i) for i in range(batch.num_columns)]
    return [[tables.plain(value) for value in values] for values in zip(*columns, strict=True)]


def _open(store: ObjectStore, key: str, size: int, loop: asyncio.AbstractEventLoop) -> pq.ParquetFile:
    return pq.ParquetFile(io.BufferedReader(_StoredRange(store, key, size, loop), BUFFER_BYTES))


async def _in_thread[T](work: Callable[[asyncio.AbstractEventLoop], T]) -> T:
    loop = asyncio.get_running_loop()
    return await asyncio.to_thread(work, loop)


async def page(store: ObjectStore, key: str, size: int, offset: int, count: int) -> list[list[Any]]:
    """`count` rows from the row `offset` of a Parquet object: only the row groups that hold them are read."""

    def read(loop: asyncio.AbstractEventLoop) -> list[list[Any]]:
        file = _open(store, key, size, loop)
        groups, first = [], 0
        for index in range(file.num_row_groups):
            rows = file.metadata.row_group(index).num_rows
            if first + rows > offset and first < offset + count:
                groups.append((index, first))
            first += rows
        found: list[list[Any]] = []
        for index, start in groups:
            rows = _rows(file.read_row_group(index))
            found.extend(rows[max(0, offset - start) : max(0, offset + count - start)])
        return found[:count]

    return await _in_thread(read)


async def matching(store: ObjectStore, key: str, size: int, needle: str) -> list[list[Any]]:
    """The rows of a Parquet object that contain `needle` (lowercase) in a cell, one row group at a time."""

    def read(loop: asyncio.AbstractEventLoop) -> list[list[Any]]:
        file = _open(store, key, size, loop)
        found: list[list[Any]] = []
        for index in range(file.num_row_groups):
            found.extend(
                row
                for row in _rows(file.read_row_group(index))
                if any(needle in str(cell).lower() for cell in row if cell is not None)
            )
        return found

    return await _in_thread(read)
