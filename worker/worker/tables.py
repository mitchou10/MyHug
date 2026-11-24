"""Counting the rows and finding the columns of the files that hold them: csv, tsv, jsonl and parquet.

A file is an open binary file on disk: it is read as it goes, never loaded whole. The API has its own reading, for the
preview of a dataset; this one only answers what the API asks of the worker."""

import csv
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import islice
from typing import Any, BinaryIO

import pyarrow as pa
import pyarrow.parquet as pq

from worker.errors import UnreadableFile as UnreadableDataFile

CSV, TSV, JSONL, PARQUET = ".csv", ".tsv", ".jsonl", ".parquet"
DATA_SUFFIXES = {CSV, TSV, JSONL, ".ndjson", PARQUET}
csv.field_size_limit(16 * 1024 * 1024)  # a cell of a few megabytes is a text, not an error
# A column is typed from its first rows: a file can be huge.
SAMPLE_ROWS = 200


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


def _binary(source: BinaryIO) -> BinaryIO:
    source.seek(0)
    return source


def convert_cell(cell: str) -> Any:
    """A cell of a csv as the number or the boolean it looks like. An empty one is nothing."""
    if cell == "":
        return None
    for cast in (int, float):
        try:
            return cast(cell)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(cell.lower(), cell)


def _text(source: BinaryIO) -> io.TextIOWrapper:
    return io.TextIOWrapper(_binary(source), encoding="utf-8-sig", newline="")


def csv_rows(source: BinaryIO, delimiter: str, path: str) -> Iterator[list[str]]:
    text = _text(source)
    try:
        yield from csv.reader(text, delimiter=delimiter)
    except UnicodeDecodeError:
        raise UnreadableDataFile(f"{path} is not text in UTF-8") from None
    except csv.Error as error:
        raise UnreadableDataFile(f"{path} is not a valid csv: {error}") from None
    finally:
        text.detach()  # the caller keeps the file


def jsonl_objects(source: BinaryIO, path: str) -> Iterator[dict[str, Any]]:
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


def _parquet(source: BinaryIO, path: str) -> pq.ParquetFile:
    try:
        return pq.ParquetFile(_binary(source))
    except (pa.ArrowException, OSError, ValueError):
        raise UnreadableDataFile(f"{path} is not a Parquet file") from None


def inspect(path: str, source: BinaryIO) -> TableInfo:
    """How many rows a file has and what its columns are. Raises UnreadableDataFile."""
    kind = suffix_of(path)
    if kind == PARQUET:
        file = _parquet(source, path)
        return TableInfo(
            file.metadata.num_rows, [Column(field.name, _dtype_of_arrow(field.type)) for field in file.schema_arrow]
        )
    if kind in (CSV, TSV):
        rows = csv_rows(source, "\t" if kind == TSV else ",", path)
        header = next(rows, None)
        if not header or not any(name.strip() for name in header):
            raise UnreadableDataFile(f"{path} has no header")
        names = [name.strip() for name in header]
        sample = [[convert_cell(cell) for cell in row] for row in islice(rows, SAMPLE_ROWS)]
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
    for item in jsonl_objects(source, path):
        count += 1
        if count <= SAMPLE_ROWS:
            sample_objects.append(item)
            names.extend(key for key in item if key not in names)
    return TableInfo(
        count, [Column(name, _dtype_of_values([row[name] for row in sample_objects if name in row])) for name in names]
    )
