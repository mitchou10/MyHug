import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DatasetFile, DatasetUpload, DatasetUploadFile, DatasetVersion
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services import tables
from app.services.dataset_versions import NamedUpload
from tests.conftest import MemoryStore
from tests.reading import Reader
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


def processor(db: AsyncSession, store: MemoryStore) -> Reader:
    return Reader(db, store)


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


# ---- what the worker adds: the fingerprint of a file sent in parts, the twins, the attempts


async def sent_in_parts(db: AsyncSession, store: MemoryStore, version: DatasetVersion, path: str, data: bytes) -> str:
    """Makes a file of the version look like one that came in parts: an object of its own, and no fingerprint."""
    key = f"datasets/{version.dataset_id}/upload-{path}"
    store.objects[key] = MemoryStore.stored(data)
    await db.execute(
        update(DatasetFile)
        .where(DatasetFile.version_id == version.id, DatasetFile.path == path)
        .values(storage_key=key, sha256=None, size_bytes=len(data))
    )
    await db.commit()
    return key


async def test_a_file_sent_in_parts_gets_the_fingerprint_the_worker_computes(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV))
    key = await sent_in_parts(db, store, version, "train.csv", CSV)
    await processor(db, store).process(version.id)
    (file,) = await DatasetVersionRepository(db).files(version.id)
    assert file.sha256 == hashlib.sha256(CSV).hexdigest() and file.storage_key == key and file.rows == 3


async def test_a_file_sent_in_parts_that_the_dataset_holds_already_is_stored_once(db: AsyncSession) -> None:
    store = MemoryStore()
    first = await setup(db, store, ("a.csv", CSV))
    (original,) = await DatasetVersionRepository(db).files(first.id)
    second = await setup(db, store, ("b.csv", CSV))
    duplicate = await sent_in_parts(db, store, second, "b.csv", CSV)
    await processor(db, store).process(second.id)
    files = {f.path: f for f in await DatasetVersionRepository(db).files(second.id)}
    assert files["b.csv"].storage_key == original.storage_key  # it points to the one that was there
    assert duplicate not in store.objects  # and the copy is gone


async def test_a_fingerprint_that_is_not_the_one_announced_fails_the_version(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV))
    await sent_in_parts(db, store, version, "train.csv", CSV)
    (file,) = await DatasetVersionRepository(db).files(version.id)
    upload = DatasetUpload(
        id=uuid.uuid4(),
        dataset_id=version.dataset_id,
        created_by="ada",
        created_by_username="ada",
        expires_at=datetime.now(UTC),
        remove=[],
    )
    db.add(upload)
    await db.flush()
    db.add(
        DatasetUploadFile(
            id=file.id,
            upload_id=upload.id,
            path="train.csv",
            size_bytes=len(CSV),
            sha256="0" * 64,
            content_type="text/csv",
            storage_key=file.storage_key,
            multipart_id="m",
            part_size=5 * 1024 * 1024,
            parts_count=1,
        )
    )
    await db.commit()
    done = await processor(db, store).process(version.id)
    assert done is not None and done.status == "failed" and "announced" in (done.error or "")


async def test_a_version_is_taken_by_one_worker_at_a_time(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV))
    versions_ = DatasetVersionRepository(db)
    stale = datetime.now(UTC) - timedelta(minutes=30)
    assert await versions_.claim(version.id, stale) is not None
    assert await versions_.claim(version.id, stale) is None  # being read
    await versions_.release(version.id)
    taken = await versions_.claim(version.id, stale)
    assert taken is not None and taken.attempts == 2


async def test_a_version_whose_worker_died_is_taken_again_after_a_while(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV))
    await DatasetVersionRepository(db).claim(version.id, datetime.now(UTC))
    await db.execute(update(DatasetVersion).values(processing_started_at=datetime.now(UTC) - timedelta(hours=1)))
    await db.commit()
    done = await processor(db, store).process(version.id)
    assert done is not None and done.status == "ready"


async def test_a_version_that_keeps_being_interrupted_ends_failed(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV))
    await db.execute(update(DatasetVersion).values(attempts=3))
    await db.commit()
    done = await processor(db, store).process(version.id)
    assert done is not None and done.status == "failed" and "interrupted" in (done.error or "")


async def test_the_sweep_finds_the_versions_nobody_is_reading(db: AsyncSession) -> None:
    store = MemoryStore()
    old = await setup(db, store, ("a.csv", CSV))
    await setup(db, store, ("b.csv", b"n\n5\n"))  # too recent: its job is probably about to start
    await db.execute(
        update(DatasetVersion)
        .where(DatasetVersion.id == old.id)
        .values(created_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db.commit()
    now = datetime.now(UTC)
    found = await DatasetVersionRepository(db).waiting(
        older_than=now - timedelta(minutes=2), stale_before=now - timedelta(minutes=30), limit=10
    )
    assert found == [old.id]
