import csv
import datetime
import decimal
import sys

import pytest

from myhug import _rows, errors


def test_a_parquet_file_gives_plain_values(tmp_path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "when": [datetime.datetime(2026, 11, 1, 9, 0), None],
            "day": [datetime.date(2026, 11, 1), None],
            "price": pa.array([decimal.Decimal("1.50"), None], pa.decimal128(5, 2)),
            "blob": [b"abc", None],
            "ratio": [float("nan"), 2.5],
            "tags": [["a", "b"], None],
            "meta": [{"k": 1}, None],
        }
    )
    path = tmp_path / "t.parquet"
    pq.write_table(table, path)
    first, second = list(_rows.file_rows("t.parquet", str(path)))
    assert first == {
        "when": "2026-11-01T09:00:00",
        "day": "2026-11-01",
        "price": 1.5,
        "blob": "<3 bytes>",
        "ratio": None,  # nan is nothing
        "tags": ["a", "b"],
        "meta": {"k": 1},
    }
    assert second["ratio"] == 2.5 and second["when"] is None


def test_a_parquet_file_needs_pyarrow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)  # as if it were not installed
    with pytest.raises(errors.MissingDependency, match=r"myhug\[parquet\]"):
        list(_rows.parquet_rows("t.parquet", "nowhere"))


def test_a_csv_with_no_header_is_refused(tmp_path) -> None:
    path = tmp_path / "a.csv"
    path.write_bytes(b"  ,  \n1,2\n")
    with pytest.raises(errors.UnreadableRows, match="no header"):
        list(_rows.file_rows("a.csv", str(path)))


def test_a_csv_that_the_reader_cannot_read_is_an_error_of_the_sdk(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args, **kwargs):
        raise csv.Error("line contains NUL")

    path = tmp_path / "a.csv"
    path.write_bytes(b"a\n1\n")
    monkeypatch.setattr(csv, "reader", broken)
    with pytest.raises(errors.UnreadableRows, match="not a valid csv"):
        list(_rows.file_rows("a.csv", str(path)))


def test_the_kind_of_a_file_comes_from_its_name() -> None:
    assert [_rows.suffix_of(p) for p in ("a/b.CSV", "x.tar.gz", "noext", "dir.d/file")] == [".csv", ".gz", "", ""]
    assert _rows.is_readable("data/train.ndjson") and not _rows.is_readable("a.png")
    with pytest.raises(errors.UnsupportedFormat):
        _rows.parser_for("a.png")


def test_cells_are_read_like_the_preview_reads_them() -> None:
    assert [_rows.convert(c) for c in ("", "7", "7.5", "True", "false", "007x", "1e3")] == [
        None, 7, 7.5, True, False, "007x", 1000.0,
    ]  # fmt: skip


def test_lines_come_whole_whatever_the_size_of_the_pieces() -> None:
    lines = _rows.Lines("a.csv")
    pieces = [b"a,b\n1,", b"2\n3", b",4"]
    found = [line for piece in pieces for line in lines.feed(piece)] + lines.feed(b"", last=True)
    assert found == ["a,b\n", "1,2\n", "3,4"]


def test_a_character_cut_between_two_pieces_is_not_lost() -> None:
    lines = _rows.Lines("a.csv")
    data = "é\n".encode()
    assert lines.feed(data[:1]) == [] and lines.feed(data[1:]) == ["é\n"]
