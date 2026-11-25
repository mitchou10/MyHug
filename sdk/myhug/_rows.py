"""Reading the rows of the files of a dataset: csv, tsv, jsonl (and parquet, with `pyarrow`).

The parsers take what comes, line after line, so that the same code reads a file on disk and a stream from the
storage, blocking or not. A row is a dict by column. Cells are read as the platform's preview reads them: a csv cell is
the integer, the float or the boolean it looks like, an empty one is `None`, a line shorter than the header is
completed with `None` and a longer one is cut."""

import codecs
import csv
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from myhug.errors import MissingDependency, MyHugError, UnreadableRows, UnsupportedFormat

csv.field_size_limit(16 * 1024 * 1024)  # a cell of a few megabytes is a text, not an error
CSV, TSV, JSONL, PARQUET = ".csv", ".tsv", ".jsonl", ".parquet"
READABLE = {CSV, TSV, JSONL, ".ndjson", PARQUET}


def suffix_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def is_readable(path: str) -> bool:
    return suffix_of(path) in READABLE


def convert(cell: str) -> Any:
    """A cell of a csv as the number or the boolean it looks like. An empty one is nothing."""
    if cell == "":
        return None
    for cast in (int, float):
        try:
            return cast(cell)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(cell.lower(), cell)


class Lines:
    """Cuts bytes that arrive in pieces into lines (each keeps its newline), decoding UTF-8 (a BOM is dropped)."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._decoder = codecs.getincrementaldecoder("utf-8-sig")()
        self._rest = ""

    def feed(self, data: bytes, *, last: bool = False) -> list[str]:
        try:
            self._rest += self._decoder.decode(data, final=last)
        except UnicodeDecodeError:
            raise UnreadableRows(f"{self._path} is not text in UTF-8") from None
        lines = self._rest.split("\n")
        self._rest = lines.pop()
        found = [line + "\n" for line in lines]
        if last and self._rest:
            found.append(self._rest)
            self._rest = ""
        return found


class CsvRows:
    """A csv, line after line. A record is complete when its quotes are balanced (a cell may hold line breaks)."""

    def __init__(self, path: str, delimiter: str = ",") -> None:
        self._path = path
        self._delimiter = delimiter
        self._pending = ""
        self._header: list[str] | None = None

    def feed(self, line: str) -> list[dict[str, Any]]:
        self._pending += line
        if self._pending.count('"') % 2:
            return []  # inside a quoted cell: the record goes on on the next line
        record, self._pending = self._pending, ""
        try:
            cells = next(csv.reader([record], delimiter=self._delimiter), [])
        except csv.Error as error:
            raise UnreadableRows(f"{self._path} is not a valid csv: {error}") from None
        if self._header is None:
            if not any(name.strip() for name in cells):
                raise UnreadableRows(f"{self._path} has no header")
            self._header = [name.strip() for name in cells]
            return []
        values = [convert(cell) for cell in cells[: len(self._header)]]
        values += [None] * (len(self._header) - len(values))
        return [dict(zip(self._header, values, strict=True))]

    def finish(self) -> list[dict[str, Any]]:
        if self._pending:
            raise UnreadableRows(f"{self._path} ends inside a quoted cell")
        return []


class JsonlRows:
    """A file of one JSON object a line. Blank lines are skipped."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._number = 0

    def feed(self, line: str) -> list[dict[str, Any]]:
        self._number += 1
        if not line.strip():
            return []
        try:
            item = json.loads(line)
        except ValueError:
            raise UnreadableRows(f"{self._path}: line {self._number} is not JSON") from None
        if not isinstance(item, dict):
            raise UnreadableRows(f"{self._path}: line {self._number} is not a JSON object")
        return [item]

    def finish(self) -> list[dict[str, Any]]:
        return []


Parser = CsvRows | JsonlRows


def parser_for(path: str) -> Parser:
    """The parser of a text file by its name, or UnsupportedFormat (parquet is read by `parquet_rows`)."""
    kind = suffix_of(path)
    if kind in (CSV, TSV):
        return CsvRows(path, "\t" if kind == TSV else ",")
    if kind in (JSONL, ".ndjson"):
        return JsonlRows(path)
    raise UnsupportedFormat(f"The rows of {path} cannot be read here: only csv, tsv, jsonl and parquet files can")


def text_rows(path: str, source: str) -> Iterator[dict[str, Any]]:
    """The rows of a csv, tsv or jsonl file on disk, read as it goes."""
    parser, lines = parser_for(path), Lines(path)
    with open(source, "rb") as handle:
        while block := handle.read(1024 * 1024):
            for line in lines.feed(block):
                yield from parser.feed(line)
    for line in lines.feed(b"", last=True):
        yield from parser.feed(line)
    yield from parser.finish()


def have_pyarrow() -> bool:
    import importlib.util

    return importlib.util.find_spec("pyarrow") is not None


def parquet_rows(path: str, source: Any) -> Iterator[dict[str, Any]]:
    """The rows of a Parquet file: a path on disk, or an open file (read by ranges, see `_ranges`)."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise MissingDependency('Reading a Parquet file needs pyarrow: pip install "myhug[parquet]"') from None
    try:
        file = pq.ParquetFile(source)
        # One group of rows at a time, and no reading ahead: what is held is a group, whatever the size of the file,
        # and a reader that stops early has not fetched the groups it did not reach.
        for group in range(file.num_row_groups):
            for batch in file.iter_batches(batch_size=8192, row_groups=[group], use_threads=False):
                yield from (_plain_row(row) for row in batch.to_pylist())
    except Exception as error:  # noqa: BLE001 - pyarrow has several error types for a file that is not Parquet
        if isinstance(error, MyHugError):  # the storage failed, or the file is not what its name says
            raise
        raise UnreadableRows(f"{path} is not a Parquet file") from None


def file_rows(path: str, source: str) -> Iterator[dict[str, Any]]:
    """The rows of any readable file on disk."""
    if suffix_of(path) == PARQUET:
        return parquet_rows(path, source)
    return text_rows(path, source)


def _plain_row(row: dict[str, Any]) -> dict[str, Any]:
    return {name: _plain(value) for name, value in row.items()}


def _plain(value: Any) -> Any:
    """What can go in JSON, as the platform's preview gives it: dates as text, bytes by their size."""
    import datetime
    import decimal
    import math

    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return str(value)


async def abatches(rows: Iterator[dict[str, Any]], size: int = 500) -> "AsyncIterator[dict[str, Any]]":
    """The rows of a blocking reader (a file on disk) for asyncio: they are read a batch at a time in a thread, so that
    reading a big file does not stop the loop."""
    import asyncio
    from itertools import islice

    while batch := await asyncio.to_thread(lambda: list(islice(rows, size))):
        for row in batch:
            yield row
