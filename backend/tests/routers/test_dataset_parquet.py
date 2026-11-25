"""A file as Parquet, to read by ranges: the file itself when it is one, else the copy the system made of it."""

import io
from collections.abc import Awaitable, Callable

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import DatasetFileDerivative
from tests.conftest import MemoryStore
from tests.routers import test_dataset_files
from tests.routers.test_dataset_files import ADDRESS, TRAIN, part, push, start
from tests.services.test_dataset_derivatives import worker_makes

work = test_dataset_files.work  # the same worker as the other tests of the files


@pytest.fixture(autouse=True)
def small_files_are_copied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DERIVATIVE_MIN_BYTES", 0)


async def pending_copy(db: AsyncSession) -> DatasetFileDerivative:
    return (await db.execute(select(DatasetFileDerivative))).scalar_one()


async def files(client) -> dict[str, dict]:
    return {f["path"]: f for f in (await client.get(f"{ADDRESS}/files")).json()}


async def test_a_table_is_columnar_once_its_copy_is_ready_and_not_before(
    client, login, work: Callable[[], Awaitable[None]], db: AsyncSession, store: MemoryStore
) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN), part("README.md", b"# hi", "text/markdown"))
    await work()
    assert (await files(client))["train.csv"]["columnar"] is False  # the copy is only waiting for a worker
    assert (await client.get(f"{ADDRESS}/files/train.csv", params={"format": "parquet"})).status_code == 404
    await worker_makes(db, store, await pending_copy(db), TRAIN)
    listed = await files(client)
    assert listed["train.csv"]["columnar"] is True
    assert listed["README.md"]["columnar"] is False  # not a table: nothing to copy


async def test_the_copy_is_given_as_a_signed_address_that_holds_the_same_rows(
    client, login, work, db: AsyncSession, store: MemoryStore
) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    await work()
    copy = await pending_copy(db)
    await worker_makes(db, store, copy, TRAIN)
    answer = await client.get(f"{ADDRESS}/files/train.csv", params={"format": "parquet"})
    assert answer.status_code == 302
    key = (await pending_copy(db)).storage_key
    assert key and answer.headers["location"] == f"memory://get/{key}"
    assert key != "train.csv" and key.startswith("derived/")  # the copy, not the file
    assert pq.read_table(io.BytesIO(store.objects[key].data)).num_rows == 5


async def test_the_raw_download_is_still_the_file_of_the_user(
    client, login, work, db: AsyncSession, store: MemoryStore
) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    await work()
    await worker_makes(db, store, await pending_copy(db), TRAIN)
    raw = await client.get(f"{ADDRESS}/files/train.csv")
    assert raw.headers["location"].startswith("memory://get/datasets/")
    same = await client.get(f"{ADDRESS}/files/train.csv", params={"format": "raw"})
    assert same.headers["location"] == raw.headers["location"]


async def test_a_parquet_file_is_its_own_columnar_form(client, login, work) -> None:
    await start(client, login)
    buffer = io.BytesIO()
    pq.write_table(pa.table({"id": [1, 2]}), buffer)
    await push(client, part("train.parquet", buffer.getvalue(), "application/octet-stream"))
    await work()
    assert (await files(client))["train.parquet"]["columnar"] is True
    answer = await client.get(f"{ADDRESS}/files/train.parquet", params={"format": "parquet"})
    assert answer.status_code == 302 and answer.headers["location"].startswith("memory://get/datasets/")


async def test_asking_a_copy_does_not_count_as_a_download(
    client, login, work, db: AsyncSession, store: MemoryStore
) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    await work()
    await worker_makes(db, store, await pending_copy(db), TRAIN)
    await client.get(f"{ADDRESS}/files/train.csv", params={"format": "parquet"})
    assert (await client.get(ADDRESS)).json()["downloads"] == 0
    await client.get(f"{ADDRESS}/files/train.csv")
    assert (await client.get(ADDRESS)).json()["downloads"] == 1


async def test_a_file_that_is_not_there_and_a_wrong_format(client, login) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    assert (await client.get(f"{ADDRESS}/files/nothing.csv", params={"format": "parquet"})).status_code == 404
    assert (await client.get(f"{ADDRESS}/files/train.csv", params={"format": "feather"})).status_code == 422


async def test_a_private_dataset_gives_no_copy_to_a_stranger(
    client, login, work, db: AsyncSession, store: MemoryStore
) -> None:
    login("u1", "ada")
    from tests.routers.test_datasets import create

    await create(client, visibility="private")
    await push(client, part("train.csv", TRAIN))
    await work()
    await worker_makes(db, store, await pending_copy(db), TRAIN)
    login("u2", "bob")
    assert (await client.get(f"{ADDRESS}/files/train.csv", params={"format": "parquet"})).status_code == 404
    assert (await client.get(f"{ADDRESS}/files")).status_code == 404


async def test_a_copy_that_left_the_storage_is_not_given(
    client, login, work, db: AsyncSession, store: MemoryStore
) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    await work()
    copy = await pending_copy(db)
    await worker_makes(db, store, copy, TRAIN)
    store.objects.pop((await pending_copy(db)).storage_key)
    assert (await client.get(f"{ADDRESS}/files/train.csv", params={"format": "parquet"})).status_code == 404
