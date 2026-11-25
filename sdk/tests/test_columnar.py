"""Rows read by ranges from Parquet: a file of any size takes the memory of a group of rows, and nothing on disk."""

import io
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from myhug import _rows, errors
from myhug._ranges import RangeFile
from tests.fake import FakePlatform
from tests.helpers import collect, get, run

ROWS = 200


def parquet(rows: int = ROWS, group: int = 50) -> bytes:
    sink = io.BytesIO()
    table = pa.table({"id": list(range(rows)), "text": [f"row {i}" for i in range(rows)]})
    pq.write_table(table, sink, row_group_size=group)
    return sink.getvalue()


CSV = b"id,text\n" + b"".join(f"{i},row {i}\n".encode() for i in range(ROWS))
EXPECTED = [{"id": i, "text": f"row {i}"} for i in range(ROWS)]


def with_copy(platform: FakePlatform, address: str = "ada/sentiment", data: bytes | None = None):
    """A dataset whose `train.csv` has a copy in Parquet that is ready."""
    entity = platform.catalog.add("datasets", address, {"train.csv": CSV})
    entity.latest()["parquet"] = {"train.csv": data or parquet()}
    return entity


def gets(platform: FakePlatform) -> list[dict]:
    return [h for m, _, h in platform.storage_calls if m == "GET"]


async def test_the_listing_says_which_files_are_columnar(driver, platform) -> None:
    with_copy(platform)
    dataset = await get(driver, "datasets", "ada/sentiment")
    assert [(f.path, f.columnar) for f in await run(driver, dataset.files)] == [("train.csv", True)]


async def test_a_table_with_a_copy_is_streamed_from_the_copy_by_ranges(driver, platform, tmp_path) -> None:
    with_copy(platform)
    dataset = await get(driver, "datasets", "ada/sentiment")
    rows = await collect(driver, lambda: dataset.iter_rows(streaming=True))
    assert rows == EXPECTED
    assert platform.catalog.parquet_asked == ["train.csv"]
    assert all("range" in h for h in gets(platform))  # never the whole file in one go
    assert not (tmp_path / "cache" / "datasets").exists()  # and nothing kept on disk
    assert not [
        r for r in platform.api_calls("GET") if r.url.path.endswith("train.csv") and "format" not in r.url.params
    ]


async def test_it_asks_for_much_less_than_the_file_when_only_a_few_rows_are_read(driver, platform) -> None:
    rows = 300_000
    sink = io.BytesIO()
    table = pa.table({"id": list(range(rows)), "text": [os.urandom(8).hex() for _ in range(rows)]})  # no compression
    pq.write_table(table, sink, row_group_size=25_000)
    data = sink.getvalue()
    assert len(data) > 5 * 1024 * 1024
    platform.catalog.add("datasets", "ada/big", {"train.csv": b"id,text\n1,a\n"}).latest()["parquet"] = {
        "train.csv": data
    }
    dataset = await get(driver, "datasets", "ada/big")
    if driver.mode == "sync":
        stream = dataset.iter_rows(streaming=True)
        first = next(stream)
        stream.close()
    else:
        stream = dataset.iter_rows(streaming=True)
        first = await anext(stream)
        await stream.aclose()
    assert first["id"] == 0
    fetched = sum(
        int(h["range"].split("=")[1].split("-")[1]) - int(h["range"].split("=")[1].split("-")[0]) + 1
        for h in gets(platform)
    )
    assert fetched < len(data) / 2  # a few rows are not the whole file


async def test_a_parquet_file_is_streamed_by_ranges_too(driver, platform) -> None:
    data = parquet()
    platform.catalog.add("datasets", "ada/p", {"train.parquet": data}).latest()["parquet"] = {"train.parquet": data}
    dataset = await get(driver, "datasets", "ada/p")
    assert await collect(driver, lambda: dataset.iter_rows(streaming=True)) == EXPECTED
    assert platform.catalog.parquet_asked == ["train.parquet"]


async def test_the_same_dataset_is_read_the_same_whichever_way(driver, platform) -> None:
    with_copy(platform)
    dataset = await get(driver, "datasets", "ada/sentiment")
    streamed = await collect(driver, lambda: dataset.iter_rows(streaming=True))
    saved = await collect(driver, lambda: dataset.iter_rows())  # the raw csv, typed by the SDK
    assert streamed == saved == EXPECTED


async def test_a_copy_that_went_away_is_replaced_by_the_file_itself(driver, platform) -> None:
    entity = with_copy(platform)
    dataset = await get(driver, "datasets", "ada/sentiment")
    del entity.latest()["parquet"]["train.csv"]  # listed as columnar when it was read, gone by now
    entity.latest()["parquet"]["train.csv"] = b""
    platform.catalog.pick(entity, None)["parquet"].pop("train.csv")
    # The listing is read before the copy is asked for: make the listing still say it is there.
    original = platform.catalog.handle

    def lying(request, body):
        answer = original(request, body)
        if request.url.path.endswith("/files") and answer is not None and answer.status_code == 200:
            import httpx2

            rows = [{**row, "columnar": True} for row in answer.json()]
            return httpx2.Response(200, json=rows)
        return answer

    platform.catalog.handle = lying  # type: ignore[method-assign]
    assert await collect(driver, lambda: dataset.iter_rows(streaming=True)) == EXPECTED
    assert platform.catalog.parquet_asked == ["train.csv"]  # asked, refused, then the csv was streamed


async def test_an_address_that_expires_while_reading_is_asked_for_again(driver, platform) -> None:
    with_copy(platform)
    dataset = await get(driver, "datasets", "ada/sentiment")
    platform.refuse_gets = 0
    original = platform.storage
    seen = {"count": 0}

    def expiring(request):
        if request.method == "GET":
            seen["count"] += 1
            if seen["count"] == 2:  # the first stretch after the size
                import httpx2

                return httpx2.Response(403)
        return original(request)

    platform.storage = expiring  # type: ignore[method-assign]
    assert await collect(driver, lambda: dataset.iter_rows(streaming=True)) == EXPECTED
    assert len(platform.catalog.parquet_asked) == 2  # the address was asked for twice


async def test_a_table_without_a_copy_is_streamed_as_text(driver, platform) -> None:
    platform.catalog.add("datasets", "ada/sentiment", {"train.csv": CSV})
    dataset = await get(driver, "datasets", "ada/sentiment")
    assert await collect(driver, lambda: dataset.iter_rows(streaming=True)) == EXPECTED
    assert platform.catalog.parquet_asked == []


async def test_without_pyarrow_the_text_is_streamed(driver, platform, monkeypatch: pytest.MonkeyPatch) -> None:
    with_copy(platform)
    monkeypatch.setattr(_rows, "have_pyarrow", lambda: False)
    dataset = await get(driver, "datasets", "ada/sentiment")
    assert await collect(driver, lambda: dataset.iter_rows(streaming=True)) == EXPECTED
    assert platform.catalog.parquet_asked == []


async def test_a_storage_that_fails_while_reading_is_an_error_not_a_bad_file(driver, platform) -> None:
    with_copy(platform)
    dataset = await get(driver, "datasets", "ada/sentiment")
    original = platform.storage
    calls = {"n": 0}

    def failing(request):
        if request.method == "GET":
            calls["n"] += 1
            if calls["n"] > 1:  # the size is told, then the first stretch fails
                import httpx2

                return httpx2.Response(500)
        return original(request)

    platform.storage = failing  # type: ignore[method-assign]
    with pytest.raises(errors.ApiError, match="refused the download"):
        await collect(driver, lambda: dataset.iter_rows(streaming=True))


# ---- the file open over ranges


def served(data: bytes, log: list[tuple[int, int]], *, total: bool = True):
    def fetch(start: int, end: int) -> tuple[bytes, int | None]:
        log.append((start, end))
        return data[start:end], len(data) if total else None

    return fetch


def test_a_range_file_reads_like_a_file_and_asks_for_a_stretch_not_a_byte() -> None:
    data = bytes(range(256)) * 20_000  # 5 MB
    log: list[tuple[int, int]] = []
    file = RangeFile(served(data, log))
    assert file.size == len(data) and file.seekable() and file.readable()
    file.seek(1000)
    assert file.read(10) == data[1000:1010] and file.tell() == 1010
    assert file.read(10) == data[1010:1020]
    assert len(log) == 2  # the size, and one stretch for both reads
    file.seek(-5, 2)
    assert file.read() == data[-5:]
    file.seek(len(data) + 10)
    assert file.read(4) == b""  # past the end is the end
    file.seek(0)
    assert file.read(len(data)) == data  # a read longer than a stretch is made of several


def test_a_storage_that_does_not_say_how_large_the_file_is_is_an_error() -> None:
    with pytest.raises(errors.ConnectionFailed, match="how large"):
        RangeFile(served(b"abc", [], total=False))


def test_a_storage_that_gives_less_than_was_asked_is_an_error() -> None:
    def short(start: int, end: int) -> tuple[bytes, int | None]:
        return b"ab", 100

    file = RangeFile(short)
    with pytest.raises(errors.ConnectionFailed, match="less than"):
        file.read(50)
