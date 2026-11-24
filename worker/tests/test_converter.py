import io
import json
from typing import Any

import pyarrow.parquet as pq
import pytest

from worker import converter, tables
from worker.errors import UnreadableFile


def convert(path: str, data: bytes, *, group: int = 1000, batch_bytes: int = 64 * 1024**2):
    target = io.BytesIO()
    done = converter.convert(io.BytesIO(data), path, target, row_group_rows=group, batch_bytes=batch_bytes)
    target.seek(0)
    return done, pq.ParquetFile(target)


def rows_of(file: pq.ParquetFile) -> list[list[Any]]:
    """The rows as the API reads them back: lists and objects written as JSON text are decoded."""
    table = file.read()
    columns = []
    for index, field in enumerate(table.schema):
        values = table.column(index).to_pylist()
        decode = (field.metadata or {}).get(b"json") == b"1"
        columns.append([json.loads(v) if decode and v is not None else v for v in values])
    return [list(row) for row in zip(*columns, strict=True)]


def original(path: str, data: bytes) -> list[list[Any]]:
    """What the first reading of the file shows for a column that is of one type: the cells as the numbers and booleans
    they look like."""
    rows = tables.csv_rows(io.BytesIO(data), "\t" if path.endswith(".tsv") else ",", path)
    header = next(rows)
    return [[tables.convert_cell(c) for c in (row + [""] * len(header))[: len(header)]] for row in rows]


CSV = b"text,score,ok,ratio\ngreat,1,true,1.5\nawful,2,false,2\nfine,,true,\n"


def test_a_csv_is_written_with_the_types_of_its_columns() -> None:
    done, file = convert("a.csv", CSV)
    assert done.rows == 3
    assert [(c.name, c.dtype) for c in done.columns] == [
        ("text", "string"),
        ("score", "int"),
        ("ok", "bool"),
        ("ratio", "float"),
    ]
    assert rows_of(file) == original("a.csv", CSV)  # the same rows, the same values, empty cells as nothing


def test_the_number_of_rows_is_the_one_of_the_original_reading() -> None:
    data = b"n\n1\n\n3\n"  # a blank line is a row of nothing
    done, file = convert("a.csv", data)
    assert done.rows == tables.inspect("a.csv", io.BytesIO(data)).rows == file.metadata.num_rows == 3


def test_a_tsv_is_read_with_its_tabs() -> None:
    data = b"a\tb\n1\tx\n2\ty\n"
    _, file = convert("a.tsv", data)
    assert rows_of(file) == [[1, "x"], [2, "y"]]


def test_a_column_that_stops_being_a_number_is_text_for_all_its_rows() -> None:
    """The type is found over every row, not guessed from the first ones: the row that does not fit would break it."""
    data = b"id,n\n" + b"".join(f"{i},{i}\n".encode() for i in range(500)) + b"500,n/a\n"
    done, file = convert("a.csv", data)
    assert {c.name: c.dtype for c in done.columns} == {"id": "int", "n": "string"}
    assert rows_of(file)[-1] == [500, "n/a"] and rows_of(file)[7] == [7, "7"]


def test_text_stays_as_it_was_written() -> None:
    _, file = convert("a.csv", b"code,n\n007,1\nabc,2\n")
    assert [row[0] for row in rows_of(file)] == ["007", "abc"]  # not 7


def test_a_number_too_big_for_64_bits_is_kept_as_written() -> None:
    big = "123456789012345678901234567890"
    done, file = convert("a.csv", f"n\n{big}\n".encode())
    assert done.columns[0].dtype == "string" and rows_of(file) == [[big]]


def test_short_and_long_rows_have_the_width_of_the_header() -> None:
    _, file = convert("a.csv", b"a,b\n1\n1,2,3\n")
    assert rows_of(file) == [[1, None], [1, 2]]


def test_names_that_a_schema_cannot_hold_are_made_to_fit_but_reported_as_they_are() -> None:
    done, file = convert("a.csv", b"a,a,\n1,2,3\n")
    assert [c.name for c in done.columns] == ["a", "a", ""]
    assert len(set(file.schema_arrow.names)) == 3 and rows_of(file) == [[1, 2, 3]]


def test_a_jsonl_has_the_union_of_its_keys_and_nulls_where_one_is_missing() -> None:
    data = b'{"a": 1, "b": "x"}\n\n{"a": 2, "c": 1.5}\n'
    done, file = convert("a.jsonl", data)
    assert done.rows == 2 and [c.name for c in done.columns] == ["a", "b", "c"]
    assert rows_of(file) == [[1, "x", None], [2, None, 1.5]]


def test_lists_and_objects_are_written_as_json_and_read_back_as_they_were() -> None:
    data = b'{"tags": ["a", "b"], "meta": {"k": 1}}\n{"tags": [], "meta": {"k": 2}}\n'
    done, file = convert("a.jsonl", data)
    assert {c.name: c.dtype for c in done.columns} == {"tags": "list", "meta": "object"}
    assert rows_of(file) == [[["a", "b"], {"k": 1}], [[], {"k": 2}]]


def test_a_jsonl_column_of_mixed_types_is_text() -> None:
    done, file = convert("a.jsonl", b'{"v": 1}\n{"v": "x"}\n{"v": [1]}\n')
    assert done.columns[0].dtype == "string" and rows_of(file) == [["1"], ["x"], ["[1]"]]


def test_the_rows_are_written_in_groups_so_a_page_reads_one_group() -> None:
    data = b"n\n" + b"".join(f"{i}\n".encode() for i in range(25))
    _, file = convert("a.csv", data, group=10)
    assert [file.metadata.row_group(i).num_rows for i in range(file.num_row_groups)] == [10, 10, 5]
    assert file.metadata.row_group(0).column(0).compression == "ZSTD"


def test_a_batch_that_is_heavy_is_written_before_it_has_many_rows() -> None:
    data = b"t\n" + b"".join(b"x" * 1000 + b"\n" for _ in range(20))
    _, file = convert("a.csv", data, group=1000, batch_bytes=5000)
    assert file.num_row_groups > 1 and file.metadata.num_rows == 20


def test_an_empty_file_and_a_header_alone() -> None:
    done, file = convert("a.csv", b"a,b\n")
    assert done.rows == 0 and file.metadata.num_rows == 0
    with pytest.raises(UnreadableFile):
        convert("a.csv", b"")


@pytest.mark.parametrize(("path", "data"), [("a.jsonl", b"nope\n"), ("a.jsonl", b"[1]\n"), ("a.csv", b"\xff\xfe\x00")])
def test_a_file_that_is_not_what_its_name_says_cannot_be_converted(path: str, data: bytes) -> None:
    with pytest.raises(UnreadableFile):
        convert(path, data)


def test_the_memory_does_not_depend_on_the_size_of_the_file(tmp_path) -> None:
    """A file much bigger than the memory a batch may take is converted, and never held: the peak stays far below it."""
    import tracemalloc

    source = tmp_path / "big.csv"
    line = "x" * 90
    with source.open("w") as handle:
        handle.write("id,text\n")
        for i in range(300_000):
            handle.write(f"{i},{line}\n")
    size = source.stat().st_size  # about 28 MiB
    target = tmp_path / "big.parquet"
    tracemalloc.start()
    with source.open("rb") as src, target.open("wb") as out:
        done = converter.convert(src, "big.csv", out, row_group_rows=20_000, batch_bytes=2 * 1024**2)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert done.rows == 300_000 and pq.ParquetFile(target).metadata.num_rows == 300_000
    assert peak < size / 3, f"peak {peak} for a file of {size}"
