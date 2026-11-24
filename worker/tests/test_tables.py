import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from worker import tables
from worker.errors import UnreadableFile


def info(path: str, data: bytes) -> tables.TableInfo:
    return tables.inspect(path, io.BytesIO(data))


def test_a_csv_has_its_rows_counted_and_its_columns_typed() -> None:
    found = info("a.csv", b"text,score,ok\nhi,1.5,true\nyo,2,false\n")
    assert found.rows == 2
    assert [(c.name, c.dtype) for c in found.columns] == [("text", "string"), ("score", "float"), ("ok", "bool")]


def test_a_tsv_and_a_jsonl_are_read() -> None:
    assert info("a.tsv", b"a\tb\n1\t2\n").rows == 1
    found = info("a.jsonl", b'{"a": 1, "b": "x"}\n\n{"a": 2, "c": [1]}\n')
    assert found.rows == 2 and [c.name for c in found.columns] == ["a", "b", "c"]


def test_a_parquet_file_gives_its_rows_without_reading_them() -> None:
    sink = io.BytesIO()
    pq.write_table(pa.table({"n": [1, 2, 3], "t": ["a", "b", "c"]}), sink)
    found = info("a.parquet", sink.getvalue())
    assert found.rows == 3 and [(c.name, c.dtype) for c in found.columns] == [("n", "int"), ("t", "string")]


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("a.csv", b""),
        ("a.csv", b"\xff\xfe\x00"),
        ("a.jsonl", b"not json\n"),
        ("a.jsonl", b"[1, 2]\n"),
        ("a.parquet", b"nope"),
    ],
)
def test_a_file_that_is_not_what_its_name_says_is_unreadable(path: str, data: bytes) -> None:
    with pytest.raises(UnreadableFile):
        info(path, data)


def test_which_files_hold_rows() -> None:
    assert tables.is_data_file("data/train.parquet") and not tables.is_data_file("README.md")
