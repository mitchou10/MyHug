"""Making a Parquet copy of a csv, tsv or jsonl file.

The file is read twice, from the disk and as it goes (never whole in memory): a first time to find the type of every
column over **all** its rows, then a second time to write it with these types. A type guessed from the first rows only
would break on the row that does not fit, and a column that is an int for ten million rows and `n/a` once is a string.

What is written reads back as what the original reading shows (see `tables`): the same rows, in the same order, the
same number of rows (a blank line in a csv is a row of nothing), the same names and types of columns. Where a column
mixes types, the copy writes it as text: `1` in a column that also holds `abc` is `"1"`, not the number."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO

import pyarrow as pa
import pyarrow.parquet as pq

from worker import tables
from worker.errors import UnreadableFile

CSV_KINDS = {tables.CSV: ",", tables.TSV: "\t"}
INT64 = 2**63
# A value that is a list or an object is written as JSON text, and the field says so: the API reads it back as it was.
JSON_FIELD = {b"json": b"1"}
Cell = Any


@dataclass(frozen=True)
class Converted:
    rows: int
    columns: list[tables.Column]


class _Kinds:
    """What was seen in a column: the types of its values."""

    def __init__(self) -> None:
        self.seen: set[str] = set()

    def add(self, value: Cell) -> None:
        if value is None:
            return
        if isinstance(value, bool):
            self.seen.add("bool")
        elif isinstance(value, int):
            self.seen.add("int" if abs(value) < INT64 else "text")  # too big for 64 bits: kept as it was written
        elif isinstance(value, float):
            self.seen.add("float")
        elif isinstance(value, list | tuple):
            self.seen.add("list")
        elif isinstance(value, dict):
            self.seen.add("object")
        else:
            self.seen.add("text")

    def dtype(self) -> str:
        """The type of the column for the API, as `tables._dtype_of_values` says it for the same values."""
        seen = self.seen
        if not seen:
            return "string"
        if seen == {"bool"}:
            return "bool"
        if seen <= {"int", "bool"}:
            return "int"
        if seen <= {"int", "float", "bool"}:
            return "float"
        if seen == {"list"}:
            return "list"
        if seen == {"object"}:
            return "object"
        return "string"


def _arrow_type(dtype: str) -> pa.DataType:
    return {"bool": pa.bool_(), "int": pa.int64(), "float": pa.float64()}.get(dtype, pa.string())


def _as_text(value: Cell) -> str | None:
    """A value written as text: text as it is, anything else as JSON (so a list or a number stays readable)."""
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _cast(value: Cell, dtype: str) -> Cell:
    if value is None:
        return None
    if dtype in ("list", "object"):
        return json.dumps(value, ensure_ascii=False)
    if dtype == "int":
        return int(value)
    if dtype == "float":
        return float(value)
    if dtype == "bool":
        return bool(value)
    return _as_text(value)


def _field_names(names: list[str]) -> list[str]:
    """Names a Parquet schema can hold: not empty, not twice."""
    used: set[str] = set()
    fields = []
    for index, name in enumerate(names):
        field = name or f"column_{index}"
        while field in used:
            field = f"{field}_{index}"
        used.add(field)
        fields.append(field)
    return fields


class _Batches:
    """Rows waiting to be written: a group goes out when it has enough rows, or enough bytes whatever the rows."""

    def __init__(self, writer: pq.ParquetWriter, schema: pa.Schema, max_rows: int, max_bytes: int) -> None:
        self._writer, self._schema = writer, schema
        self._max_rows, self._max_bytes = max_rows, max_bytes
        self._columns: list[list[Cell]] = [[] for _ in schema]
        self._bytes = 0
        self.rows = 0

    def add(self, row: list[Cell]) -> None:
        for column, value in zip(self._columns, row, strict=True):
            column.append(value)
            if isinstance(value, str):
                self._bytes += len(value)
        self.rows += 1
        if len(self._columns[0]) >= self._max_rows or self._bytes >= self._max_bytes:
            self.flush()

    def flush(self) -> None:
        if not self._columns or not self._columns[0]:
            return
        arrays = [pa.array(column, type=field.type) for column, field in zip(self._columns, self._schema, strict=True)]
        self._writer.write_table(pa.Table.from_arrays(arrays, schema=self._schema), row_group_size=len(arrays[0]))
        self._columns = [[] for _ in self._schema]
        self._bytes = 0


def _csv(source: BinaryIO, path: str) -> tuple[list[str], Iterator[list[str]]]:
    """The names of the columns, and the rows as text, each as long as the header (a blank line is a row of nothing, as
    the original reading counts it). Raises UnreadableFile."""
    rows = tables.csv_rows(source, CSV_KINDS[tables.suffix_of(path)], path)
    header = next(rows, None)
    if not header or not any(name.strip() for name in header):
        raise UnreadableFile(f"{path} has no header")
    names = [name.strip() for name in header]
    width = len(names)

    def padded() -> Iterator[list[str]]:
        for row in rows:
            cells = row[:width]
            yield cells + [""] * (width - len(cells))

    return names, padded()


def convert(source: BinaryIO, path: str, target: BinaryIO, *, row_group_rows: int, batch_bytes: int) -> Converted:
    """Writes the Parquet copy of `source` (a csv, tsv or jsonl file on disk) to `target`. Raises UnreadableFile."""
    is_csv = tables.suffix_of(path) in CSV_KINDS

    # ---- first pass: the names and the type of every column
    names: list[str] = []
    kinds: list[_Kinds] = []
    count = 0
    if is_csv:
        names, rows = _csv(source, path)
        kinds = [_Kinds() for _ in names]
        for row in rows:
            count += 1
            for kind, cell in zip(kinds, row, strict=True):
                kind.add(tables.convert_cell(cell))
    else:
        index: dict[str, int] = {}
        for item in tables.jsonl_objects(source, path):
            count += 1
            for key, value in item.items():
                if key not in index:
                    index[key] = len(names)
                    names.append(key)
                    kinds.append(_Kinds())
                kinds[index[key]].add(value)
    dtypes = [kind.dtype() for kind in kinds]
    schema = pa.schema(
        [
            pa.field(field, _arrow_type(dtype), metadata=JSON_FIELD if dtype in ("list", "object") else None)
            for field, dtype in zip(_field_names(names), dtypes, strict=True)
        ]
    )

    # ---- second pass: the rows, with the types now known
    writer = pq.ParquetWriter(target, schema, compression="zstd")
    written = 0
    try:
        batches = _Batches(writer, schema, row_group_rows, batch_bytes)
        if is_csv:
            for row in _csv(source, path)[1]:
                # A column that mixes types is text as it was written (`007` stays `007`, not 7).
                batches.add(
                    [
                        (cell or None) if dtype == "string" else _cast(tables.convert_cell(cell), dtype)
                        for cell, dtype in zip(row, dtypes, strict=True)
                    ]
                )
        else:
            for item in tables.jsonl_objects(source, path):
                batches.add([_cast(item.get(name), dtype) for name, dtype in zip(names, dtypes, strict=True)])
        batches.flush()
        written = batches.rows
    finally:
        writer.close()
    if written != count:  # the two readings must see the same file
        raise UnreadableFile(f"{path} changed while it was read")
    return Converted(count, [tables.Column(name, dtype) for name, dtype in zip(names, dtypes, strict=True)])
