import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services import tables
from app.services.errors import UnreadableDataFile


def parquet(rows: dict) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.table(rows), buffer)
    return buffer.getvalue()


CSV = b"id,text,score,ok\n1,hello,0.5,true\n2,world,1.5,false\n3,,2,true\n"


def test_a_csv_gives_its_rows_and_types_its_columns_from_what_they_hold() -> None:
    info = tables.inspect("data/train.csv", CSV)
    assert info.rows == 3
    assert [(c.name, c.dtype) for c in info.columns] == [
        ("id", "int"),
        ("text", "string"),
        ("score", "float"),
        ("ok", "bool"),
    ]
    assert list(tables.iter_rows("data/train.csv", CSV)) == [
        [1, "hello", 0.5, True],
        [2, "world", 1.5, False],
        [3, None, 2, True],
    ]


def test_a_tsv_is_split_on_tabs_and_a_byte_order_mark_is_ignored() -> None:
    data = "﻿a\tb\n1\tx,y\n".encode()
    assert [c.name for c in tables.inspect("x.tsv", data).columns] == ["a", "b"]
    assert list(tables.iter_rows("x.tsv", data)) == [[1, "x,y"]]


def test_a_short_row_is_completed_with_nothing_and_a_long_one_is_cut() -> None:
    assert list(tables.iter_rows("x.csv", b"a,b\n1\n1,2,3\n")) == [[1, None], [1, 2]]


def test_jsonl_columns_are_the_keys_in_the_order_they_appear() -> None:
    data = b'{"text": "a", "label": 1}\n\n{"text": "b", "extra": [1, 2]}\n'
    info = tables.inspect("x.jsonl", data)
    assert info.rows == 2
    assert [(c.name, c.dtype) for c in info.columns] == [("text", "string"), ("label", "int"), ("extra", "list")]
    assert list(tables.iter_rows("x.jsonl", data)) == [["a", 1, None], ["b", None, [1, 2]]]


def test_parquet_gives_its_rows_and_its_types() -> None:
    data = parquet({"id": [1, 2], "price": [1.5, None], "name": ["a", "b"], "tags": [["x"], []]})
    info = tables.inspect("x.parquet", data)
    assert info.rows == 2
    assert [(c.name, c.dtype) for c in info.columns] == [
        ("id", "int"),
        ("price", "float"),
        ("name", "string"),
        ("tags", "list"),
    ]
    assert list(tables.iter_rows("x.parquet", data)) == [[1, 1.5, "a", ["x"]], [2, None, "b", []]]


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("x.csv", b""),
        ("x.csv", b"\xff\xfe\x00"),
        ("x.jsonl", b"not json"),
        ("x.jsonl", b"[1, 2]"),
        ("x.parquet", b"nope"),
    ],
)
def test_a_file_that_is_not_what_its_name_says_is_refused(path: str, data: bytes) -> None:
    with pytest.raises(UnreadableDataFile):
        tables.inspect(path, data)


@pytest.mark.parametrize(
    ("path", "split"),
    [
        ("train.csv", "train"),
        ("data/train-00000-of-00002.parquet", "train"),
        ("test.jsonl", "test"),
        ("data/validation.csv", "validation"),
        ("valid/part.csv", "validation"),
        ("dev.csv", "validation"),
        ("data.csv", "train"),
        ("latest.csv", "train"),
        ("contest.csv", "train"),
    ],
)
def test_the_split_comes_from_the_name_of_the_file(path: str, split: str) -> None:
    assert tables.split_of(path) == split


@pytest.mark.parametrize("path", ["a.csv", "a.TSV", "dir/a.jsonl", "a.ndjson", "a.parquet"])
def test_the_files_that_hold_rows(path: str) -> None:
    assert tables.is_data_file(path)


@pytest.mark.parametrize("path", ["README.md", "image.png", "csv", "dir.csv/readme"])
def test_the_files_that_do_not(path: str) -> None:
    assert not tables.is_data_file(path)


def test_what_cannot_be_written_in_json_is_turned_into_something_that_can() -> None:
    from datetime import date, datetime
    from decimal import Decimal

    assert tables.plain(float("nan")) is None
    assert tables.plain(datetime(2026, 1, 2, 3, 4)) == "2026-01-02T03:04:00"
    assert tables.plain(date(2026, 1, 2)) == "2026-01-02"
    assert tables.plain(Decimal("1.5")) == 1.5
    assert tables.plain(b"abc") == "<3 bytes>"
    assert tables.plain({1: (b"a", None)}) == {"1": ["<1 bytes>", None]}
