import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import DatasetFile, DatasetFileDerivative, DatasetUpload, DatasetUploadFile
from app.repositories.storage_references import LOCK, StorageReferenceRepository
from app.services.factory import build_storage_garbage, garbage_grace
from app.services.storage_garbage import PREFIXES, StorageGarbage
from tests.conftest import MemoryStore
from tests.reading import Reader
from tests.services.test_dataset_processing import setup

CSV = b"n\n1\n2\n"
OLD = timedelta(days=30)


def collector(db: AsyncSession, store: MemoryStore, **options) -> StorageGarbage:
    return StorageGarbage(StorageReferenceRepository(db), store, grace=timedelta(hours=24), **options)


def litter(store: MemoryStore, key: str, *, old: bool = True, data: bytes = b"x") -> str:
    store.objects[key] = MemoryStore.stored(data, "application/octet-stream")
    store.age(key, OLD if old else timedelta(0))
    return key


async def a_version(db: AsyncSession, store: MemoryStore, *files: tuple[str, bytes]):
    version = await setup(db, store, *files)
    await Reader(db, store).process(version.id)
    for key in list(store.objects):
        store.age(key, OLD)
    return version


# ---- what is garbage and what is not


async def test_an_old_object_that_nothing_points_to_is_deleted(db: AsyncSession) -> None:
    store = MemoryStore()
    key = litter(store, "datasets/d1/orphan")
    result = await collector(db, store).collect(dry_run=False)
    assert key not in store.objects
    assert (result.garbage_objects, result.deleted_objects, result.garbage_bytes) == (1, 1, 1)


async def test_an_object_that_a_file_of_a_version_points_to_is_kept(db: AsyncSession) -> None:
    store = MemoryStore()
    await a_version(db, store, ("train.csv", CSV))
    keys = set(store.objects)
    result = await collector(db, store).collect(dry_run=False)
    assert set(store.objects) == keys and result.garbage_objects == 0 and result.scanned == len(keys)


async def test_an_object_that_is_too_young_is_kept_even_if_nothing_points_to_it(db: AsyncSession) -> None:
    """It is put in the storage before its row is committed: a young object nothing points to is normal."""
    store = MemoryStore()
    key = litter(store, "datasets/d1/new", old=False)
    result = await collector(db, store).collect(dry_run=False)
    assert key in store.objects and result.garbage_objects == 0 and result.scanned == 1


async def test_an_object_of_another_dataset_that_a_file_points_to_is_kept(db: AsyncSession) -> None:
    """The key tells which dataset it was made for, not which one points to it: the references decide."""
    store = MemoryStore()
    await a_version(db, store, ("train.csv", CSV))
    (file,) = (await db.execute(select(DatasetFile))).scalars().all()
    moved = f"datasets/{uuid.uuid4()}/shared"
    store.objects[moved] = store.objects.pop(file.storage_key)
    store.age(moved, OLD)
    await db.execute(update(DatasetFile).values(storage_key=moved))
    await db.commit()
    await collector(db, store).collect(dry_run=False)
    assert moved in store.objects


async def test_an_object_that_an_open_upload_points_to_is_kept(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("a.csv", CSV))
    upload = DatasetUpload(
        id=uuid.uuid4(),
        dataset_id=version.dataset_id,
        created_by="u1",
        created_by_username="ada",
        expires_at=version.created_at + timedelta(days=1),
    )
    db.add(upload)
    await db.flush()
    key = litter(store, f"datasets/{version.dataset_id}/waiting-for-its-row")
    db.add(
        DatasetUploadFile(
            id=uuid.uuid4(),
            upload_id=upload.id,
            path="b.csv",
            size_bytes=1,
            content_type="text/csv",
            storage_key=key,
            part_size=5 * 1024**2,
            parts_count=1,
        )
    )
    await db.commit()
    await collector(db, store).collect(dry_run=False)
    assert key in store.objects
    await db.execute(update(DatasetUpload).values(status="expired"))  # the session is over: nothing points to it
    await db.commit()
    await collector(db, store).collect(dry_run=False)
    assert key not in store.objects


async def test_an_object_that_a_copy_points_to_is_kept(db: AsyncSession) -> None:
    store = MemoryStore()
    await a_version(db, store, ("train.csv", CSV))
    (file,) = (await db.execute(select(DatasetFile))).scalars().all()
    copy = litter(store, "derived/parquet/abc/copy.parquet")
    db.add(
        DatasetFileDerivative(
            source_storage_key=file.storage_key,
            source_path="train.csv",
            source_size_bytes=file.size_bytes,
            params_hash="h" * 64,
            storage_key=copy,
        )
    )
    await db.commit()
    await collector(db, store).collect(dry_run=False)
    assert copy in store.objects and file.storage_key in store.objects


# ---- the copies whose file is gone


async def test_a_copy_whose_source_is_gone_is_deleted_with_its_object(db: AsyncSession) -> None:
    store = MemoryStore()
    copy = litter(store, "derived/parquet/abc/gone.parquet")
    db.add(
        DatasetFileDerivative(
            source_storage_key="datasets/d1/nobody-holds-this",
            source_path="x.csv",
            source_size_bytes=1,
            params_hash="h" * 64,
            storage_key=copy,
        )
    )
    await db.commit()
    await db.execute(update(DatasetFileDerivative).values(updated_at=text("now() - interval '30 days'")))
    await db.commit()
    result = await collector(db, store).collect(dry_run=False)
    assert result.orphan_copies == 1 and copy not in store.objects
    assert (await db.execute(select(DatasetFileDerivative))).scalars().all() == []


async def test_a_copy_of_a_file_that_is_held_is_kept_and_a_recent_orphan_too(db: AsyncSession) -> None:
    store = MemoryStore()
    await a_version(db, store, ("train.csv", CSV))
    (file,) = (await db.execute(select(DatasetFile))).scalars().all()
    for source in (file.storage_key, "datasets/d1/just-released"):
        db.add(
            DatasetFileDerivative(
                source_storage_key=source, source_path="x.csv", source_size_bytes=1, params_hash=source[-8:].ljust(64)
            )
        )
    await db.commit()
    await db.execute(
        update(DatasetFileDerivative)
        .where(DatasetFileDerivative.source_storage_key == file.storage_key)
        .values(updated_at=text("now() - interval '30 days'"))
    )
    await db.commit()
    result = await collector(db, store).collect(dry_run=False)
    assert result.orphan_copies == 0 and len((await db.execute(select(DatasetFileDerivative))).scalars().all()) == 2


# ---- the uploads started that nobody owns


async def test_an_upload_in_parts_that_nobody_owns_is_given_up_when_old(db: AsyncSession) -> None:
    store = MemoryStore()
    old = await store.create_multipart("datasets/d1/lost", "text/csv")
    young = await store.create_multipart("datasets/d1/recent", "text/csv")
    store.age("datasets/d1/lost", OLD)
    result = await collector(db, store).collect(dry_run=False)
    assert result.started_uploads_given_up == 1 and old not in store.uploads and young in store.uploads


async def test_an_upload_that_an_open_session_or_a_copy_owns_is_not_given_up(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await setup(db, store, ("a.csv", CSV))
    session = await store.create_multipart("datasets/d1/session", "text/csv")
    writing = await store.create_multipart("derived/parquet/x/copy.parquet", "text/csv")
    for key in ("datasets/d1/session", "derived/parquet/x/copy.parquet"):
        store.age(key, OLD)
    upload = DatasetUpload(
        id=uuid.uuid4(),
        dataset_id=version.dataset_id,
        created_by="u1",
        created_by_username="ada",
        expires_at=version.created_at + timedelta(days=1),
    )
    db.add(upload)
    await db.flush()
    db.add(
        DatasetUploadFile(
            id=uuid.uuid4(),
            upload_id=upload.id,
            path="s.csv",
            size_bytes=1,
            content_type="text/csv",
            storage_key="datasets/d1/session",
            multipart_id=session,
            part_size=5 * 1024**2,
            parts_count=1,
        )
    )
    db.add(
        DatasetFileDerivative(
            source_storage_key="datasets/d1/src",
            source_path="s.csv",
            source_size_bytes=1,
            params_hash="h" * 64,
            multipart_id=writing,
        )
    )
    await db.commit()
    result = await collector(db, store).collect(dry_run=False)
    assert result.started_uploads_given_up == 0 and {session, writing} <= set(store.uploads)


# ---- care


async def test_a_dry_run_deletes_nothing_and_says_what_it_would(db: AsyncSession) -> None:
    store = MemoryStore()
    key = litter(store, "datasets/d1/orphan", data=b"12345")
    lost = await store.create_multipart("datasets/d1/lost", "text/csv")
    store.age("datasets/d1/lost", OLD)
    result = await collector(db, store).collect(dry_run=True)
    assert key in store.objects and lost in store.uploads
    assert (result.dry_run, result.garbage_objects, result.garbage_bytes, result.deleted_objects) == (True, 1, 5, 0)
    assert result.started_uploads_given_up == 1


@pytest.mark.parametrize("key", ["avatars/u1", "feedback/a/b.png", "mlflow/artifacts/1/model", "datasets", "other/x"])
async def test_nothing_outside_the_prefixes_it_owns_is_ever_touched(db: AsyncSession, key: str) -> None:
    store = MemoryStore()
    litter(store, key)
    result = await collector(db, store).collect(dry_run=False)
    assert key in store.objects and result.scanned == 0
    assert all(prefix.endswith("/") for prefix in PREFIXES)


async def test_a_pass_is_bounded_and_goes_on_from_where_it_stopped(db: AsyncSession) -> None:
    store = MemoryStore()
    keys = [litter(store, f"datasets/d1/{i:03d}") for i in range(9)]
    gc = collector(db, store, batch=2, max_scanned=4)
    first = await gc.collect(dry_run=False)
    assert first.next_after is not None and 0 < first.deleted_objects < 9
    seen = first.scanned
    after = first.next_after
    while after is not None:
        step = await gc.collect(after=after, dry_run=False)
        seen += step.scanned
        after = step.next_after
    assert seen == 9 and not [k for k in keys if k in store.objects]


async def test_a_pass_deletes_no_more_than_its_cap(db: AsyncSession) -> None:
    store = MemoryStore()
    for i in range(6):
        litter(store, f"datasets/d1/{i}")
    result = await collector(db, store, batch=2, max_deletions=3).collect(dry_run=False)
    assert result.deleted_objects == 3 and result.next_after is not None and len(store.objects) == 3


async def test_the_pass_goes_on_from_one_prefix_to_the_next(db: AsyncSession) -> None:
    store = MemoryStore()
    litter(store, "datasets/d1/a")
    litter(store, "derived/parquet/x/b")
    gc = collector(db, store, batch=1, max_scanned=1)
    first = await gc.collect(dry_run=False)
    assert first.next_after == "datasets/d1/a"
    second = await gc.collect(after=first.next_after, dry_run=False)
    assert second.next_after == "derived/parquet/x/b"
    third = await gc.collect(after=second.next_after, dry_run=False)  # `models/` has nothing: the walk is over
    assert third.next_after is None and not store.objects


async def test_a_row_whose_object_is_not_there_is_told_and_not_hidden(db: AsyncSession) -> None:
    store = MemoryStore()
    await a_version(db, store, ("train.csv", CSV))
    (file,) = (await db.execute(select(DatasetFile))).scalars().all()
    del store.objects[file.storage_key]
    result = await collector(db, store).collect(dry_run=False)
    assert result.missing_objects == 1 and result.missing_keys == [file.storage_key]
    assert (await db.execute(select(DatasetFile))).scalars().all()  # the row is left as it is


async def test_only_one_collection_runs_at_a_time(db: AsyncSession) -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as other:
        await other.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK})
        store = MemoryStore()
        key = litter(store, "datasets/d1/orphan")
        busy = await collector(db, store).collect(dry_run=False)
        assert busy.busy is True and key in store.objects
        await other.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK})
    await engine.dispose()
    assert (await collector(db, store).collect(dry_run=False)).busy is False  # and the lock is free again


async def test_the_lock_is_given_back_after_a_collection(db: AsyncSession) -> None:
    store = MemoryStore()
    for _ in range(3):
        assert (await collector(db, store).collect(dry_run=False)).busy is False


def test_the_grace_is_longer_than_an_upload_whatever_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    session = timedelta(hours=settings.UPLOAD_SESSION_HOURS)
    assert garbage_grace() > session
    monkeypatch.setattr(settings, "STORAGE_GC_GRACE_HOURS", 1)
    assert garbage_grace() > session  # too short a setting is not obeyed
    monkeypatch.setattr(settings, "STORAGE_GC_GRACE_HOURS", 24 * 30)
    assert garbage_grace() == timedelta(days=30)
    monkeypatch.setattr(settings, "UPLOAD_SESSION_HOURS", 100)
    monkeypatch.setattr(settings, "STORAGE_GC_GRACE_HOURS", 0)
    assert garbage_grace() == timedelta(hours=112)


async def test_the_built_collector_uses_the_settings(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_GC_CHECK_ROWS", 0)
    store = MemoryStore()
    await a_version(db, store, ("train.csv", CSV))
    (file,) = (await db.execute(select(DatasetFile))).scalars().all()
    del store.objects[file.storage_key]
    assert (await build_storage_garbage(db, store).collect()).missing_objects == 0  # nothing was checked
