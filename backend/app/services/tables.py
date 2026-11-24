"""Reading the files that hold rows: csv, tsv, jsonl and parquet.

A file is given as its bytes (a small one) or as an open binary file (a large one, kept on disk by the worker): it is
read as it goes, never loaded whole."""

import csv
import io
import json
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from itertools import islice
from typing import Any, BinaryIO

import pyarrow as pa
import pyarrow.parquet as pq

from app.services.errors import UnreadableDataFile

CSV, TSV, JSONL, PARQUET = ".csv", ".tsv", ".jsonl", ".parquet"
DATA_SUFFIXES = {CSV, TSV, JSONL, ".ndjson", PARQUET}
# A file is given as its bytes, or as an open binary file.
Source = bytes | BinaryIO
csv.field_size_limit(16 * 1024 * 1024)  # a cell of a few megabytes is a text, not an error
# A column is typed from its first rows: a file can be huge.
SAMPLE_ROWS = 200

# The name of a split in the name of a file: `train.csv`, `data/test-00000-of-00002.parquet`, `validation/x.jsonl`.
_SPLITS = {
    "train": "train",
    "training": "train",
    "test": "test",
    "testing": "test",
    "val": "validation",
    "valid": "validation",
    "validation": "validation",
    "dev": "validation",
}
_SPLIT_IN_PATH = re.compile(
    r"(?:^|[/._-])(train|training|test|testing|val|valid|validation|dev)(?=$|[/._-]|\d)", re.IGNORECASE
)


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str


@dataclass(frozen=True)
class TableInfo:
    rows: int
    columns: list[Column]


def suffix_of(path: str) -> str:
    return "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""


def is_data_file(path: str) -> bool:
    return suffix_of(path) in DATA_SUFFIXES


def is_convertible(path: str) -> bool:
    """A file whose rows are worth a copy in Parquet: csv, tsv and jsonl. A Parquet file already is one."""
    return is_data_file(path) and suffix_of(path) != PARQUET


def split_of(path: str) -> str:
    """The split a file belongs to, by its name. A file that does not say is the `train` split, like everywhere else."""
    found = _SPLIT_IN_PATH.search(path)
    return _SPLITS[found.group(1).lower()] if found else "train"


def plain(value: Any) -> Any:
    """What can go in JSON: dates as text, nan as nothing, bytes by their size, the rest by what it contains."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    return str(value)


def _dtype_of_values(values: list[Any]) -> str:
    kinds = {type(value) for value in values if value is not None}
    if not kinds:
        return "string"
    if kinds <= {bool}:
        return "bool"
    if kinds <= {int, bool}:
        return "int"
    if kinds <= {int, float, bool}:
        return "float"
    if kinds <= {list, tuple}:
        return "list"
    if kinds <= {dict}:
        return "object"
    return "string"


def _dtype_of_arrow(kind: pa.DataType) -> str:
    if pa.types.is_boolean(kind):
        return "bool"
    if pa.types.is_integer(kind):
        return "int"
    if pa.types.is_floating(kind) or pa.types.is_decimal(kind):
        return "float"
    if pa.types.is_list(kind) or pa.types.is_large_list(kind) or pa.types.is_fixed_size_list(kind):
        return "list"
    if pa.types.is_struct(kind) or pa.types.is_map(kind):
        return "object"
    if pa.types.is_timestamp(kind) or pa.types.is_date(kind) or pa.types.is_time(kind):
        return "datetime"
    if pa.types.is_binary(kind) or pa.types.is_large_binary(kind):
        return "bytes"
    return "string"


def _binary(source: Source) -> BinaryIO:
    handle = io.BytesIO(source) if isinstance(source, bytes) else source
    handle.seek(0)
    return handle


def _convert(cell: str) -> Any:
    """A cell of a csv as the number or the boolean it looks like. An empty one is nothing."""
    if cell == "":
        return None
    for cast in (int, float):
        try:
            return cast(cell)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(cell.lower(), cell)


def _text(source: Source) -> io.TextIOWrapper:
    return io.TextIOWrapper(_binary(source), encoding="utf-8-sig", newline="")


def _csv_rows(source: Source, delimiter: str, path: str) -> Iterator[list[str]]:
    text = _text(source)
    try:
        yield from csv.reader(text, delimiter=delimiter)
    except UnicodeDecodeError:
        raise UnreadableDataFile(f"{path} is not text in UTF-8") from None
    except csv.Error as error:
        raise UnreadableDataFile(f"{path} is not a valid csv: {error}") from None
    finally:
        text.detach()  # the caller keeps the file


def _jsonl_objects(source: Source, path: str) -> Iterator[dict[str, Any]]:
    text = _text(source)
    try:
        for number, line in enumerate(text, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                raise UnreadableDataFile(f"{path}: line {number} is not JSON") from None
            if not isinstance(item, dict):
                raise UnreadableDataFile(f"{path}: line {number} is not a JSON object")
            yield item
    except UnicodeDecodeError:
        raise UnreadableDataFile(f"{path} is not text in UTF-8") from None
    finally:
        text.detach()


def _parquet(source: Source, path: str) -> pq.ParquetFile:
    try:
        return pq.ParquetFile(_binary(source))
    except (pa.ArrowException, OSError, ValueError):
        raise UnreadableDataFile(f"{path} is not a Parquet file") from None


def inspect(path: str, source: Source) -> TableInfo:
    """How many rows a file has and what its columns are. Raises UnreadableDataFile."""
    kind = suffix_of(path)
    if kind == PARQUET:
        file = _parquet(source, path)
        return TableInfo(
            file.metadata.num_rows, [Column(field.name, _dtype_of_arrow(field.type)) for field in file.schema_arrow]
        )
    if kind in (CSV, TSV):
        rows = _csv_rows(source, "\t" if kind == TSV else ",", path)
        header = next(rows, None)
        if not header or not any(name.strip() for name in header):
            raise UnreadableDataFile(f"{path} has no header")
        names = [name.strip() for name in header]
        sample = [[_convert(cell) for cell in row] for row in islice(rows, SAMPLE_ROWS)]
        count = len(sample) + sum(1 for _ in rows)
        return TableInfo(
            count,
            [
                Column(name, _dtype_of_values([row[i] for row in sample if i < len(row)]))
                for i, name in enumerate(names)
            ],
        )
    names: list[str] = []
    sample_objects: list[dict[str, Any]] = []
    count = 0
    for item in _jsonl_objects(source, path):
        count += 1
        if count <= SAMPLE_ROWS:
            sample_objects.append(item)
            names.extend(key for key in item if key not in names)
    return TableInfo(
        count, [Column(name, _dtype_of_values([row[name] for row in sample_objects if name in row])) for name in names]
    )


def iter_rows(path: str, source: Source) -> Iterator[list[Any]]:
    """The rows of a file, as lists of plain values in the order of its columns."""
    kind = suffix_of(path)
    if kind == PARQUET:
        for batch in _parquet(source, path).iter_batches():
            columns = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
            for values in zip(*columns, strict=True):
                yield [plain(value) for value in values]
    elif kind in (CSV, TSV):
        rows = _csv_rows(source, "\t" if kind == TSV else ",", path)
        header = next(rows, [])
        for row in rows:
            cells = [_convert(cell) for cell in row[: len(header)]]
            yield cells + [None] * (len(header) - len(cells))
    else:
        names = [column.name for column in inspect(path, source).columns]
        for item in _jsonl_objects(source, path):
            yield [plain(item.get(name)) for name in names]
