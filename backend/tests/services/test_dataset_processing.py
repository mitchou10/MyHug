import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DatasetVersion
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services import tables
from app.services.dataset_processing import DatasetProcessor
from app.services.dataset_versions import NamedUpload
from tests.conftest import MemoryStore
from tests.services.test_dataset_services import ADA, FIELDS, service, versions

CSV = b"n\n1\n2\n3\n"


async def setup(db: AsyncSession, store: MemoryStore, *files: tuple[str, bytes]) -> DatasetVersion:
    """A dataset, and a version of it with these files: sent, not read."""
    if not await DatasetRepository(db).get_by_name("ada", "reviews"):
        await service(db).create(ADA, name="reviews", **FIELDS)
    uploads = [NamedUpload(path=path, data=data) for path, data in files]
    return await versions(db, store).create(ADA, "ada", "reviews", uploads=uploads, remove=[], message="")


async def dataset_rows(db: AsyncSession) -> int | None:
    """The number of rows the dataset shows in the list."""
    dataset = await DatasetRepository(db).get_by_name("ada", "reviews")
    assert dataset is not None
    return dataset.rows


def processor(db: AsyncSession, store: MemoryStore) -> DatasetProcessor:
    return DatasetProcessor(DatasetRepository(db), DatasetVersionRepository(db), store)


async def test_a_version_that_was_just_sent_has_not_been_read(db: AsyncSession) -> None:
    version = await setup(db, MemoryStore(), ("train.csv", CSV))
    assert (version.status, version.rows, version.columns, version.error) == ("pending", None, [], None)
    files = await DatasetVersionRepository(db).files(version.id)
    assert [(f.split, f.rows, f.columns) for f in files] == [(None, None, [])]


async def test_reading_a_version_makes_it_ready_with_what_is_in_its_files(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV), ("README.md", b"# x"))
    done = await processor(db, store).process(version.id)
    assert done is not None and (done.status, done.rows, done.columns) == ("ready", 3, [{"name": "n", "dtype": "int"}])
    assert await dataset_rows(db) == 3  # the list shows it


async def test_a_version_that_is_ready_is_left_alone(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV))
    await processor(db, store).process(version.id)
    monkeypatch.setattr(tables, "inspect", lambda *_: pytest.fail("a file was read again"))
    again = await processor(db, store).process(version.id)
    assert again is not None and again.status == "ready"


async def test_a_version_that_does_not_exist_is_nothing(db: AsyncSession) -> None:
    assert await processor(db, MemoryStore()).process(uuid.uuid4()) is None


async def test_the_files_already_read_in_an_earlier_version_are_not_read_again(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore()
    first = await setup(db, store, ("train.csv", CSV))
    await processor(db, store).process(first.id)
    second = await setup(db, store, ("test.csv", b"n\n9\n"))  # train.csv is carried over
    seen: list[str] = []
    real = tables.inspect
    monkeypatch.setattr(tables, "inspect", lambda path, data: (seen.append(path), real(path, data))[1])
    done = await processor(db, store).process(second.id)
    assert seen == ["test.csv"]  # train.csv was not opened
    assert done is not None and (done.status, done.rows) == ("ready", 4)


async def test_a_file_that_cannot_be_read_fails_the_version_and_says_which(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("good.csv", CSV), ("bad.parquet", b"nope"))
    done = await processor(db, store).process(version.id)
    assert done is not None and done.status == "failed" and "bad.parquet" in (done.error or "")
    assert done.rows is None
    assert await dataset_rows(db) is None


async def test_a_version_that_failed_can_be_read_again(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV))
    key = next(iter(store.objects))
    lost = store.objects.pop(key)  # the storage lost the file
    failed = await processor(db, store).process(version.id)
    assert failed is not None and failed.status == "failed" and "missing" in (failed.error or "")
    store.objects[key] = lost  # and it is back
    retried = await processor(db, store).process(version.id)
    assert retried is not None and (retried.status, retried.error, retried.rows) == ("ready", None, 3)


async def test_reading_an_old_version_does_not_change_what_the_list_shows(db: AsyncSession) -> None:
    store = MemoryStore()
    old = await setup(db, store, ("train.csv", CSV))
    latest = await setup(db, store, ("test.csv", b"n\n9\n"))
    await processor(db, store).process(old.id)
    assert await dataset_rows(db) is None  # the dataset is at version 2
    await processor(db, store).process(latest.id)
    assert await dataset_rows(db) == 4
