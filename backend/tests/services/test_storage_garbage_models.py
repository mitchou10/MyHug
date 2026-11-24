"""The collector and the files of the models: it must know what points to them, or it would delete every weight."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Model, ModelFile, ModelUpload, ModelUploadFile, ModelVersion
from tests.conftest import MemoryStore
from tests.services.test_storage_garbage import OLD, collector, litter


async def a_model_file(db: AsyncSession, store: MemoryStore) -> tuple[Model, str]:
    model = Model(id=uuid.uuid4(), owner="ada", name="m", created_by="u1", created_by_username="ada")
    db.add(model)
    await db.flush()
    version = ModelVersion(id=uuid.uuid4(), model_id=model.id, number=1, created_by="u1", created_by_username="ada")
    db.add(version)
    await db.flush()
    key = litter(store, f"models/{model.id}/files/{uuid.uuid4()}", data=b"weights")
    db.add(
        ModelFile(
            version_id=version.id,
            path="w.bin",
            size_bytes=7,
            content_type="application/octet-stream",
            storage_key=key,
        )
    )
    await db.commit()
    return model, key


async def test_an_old_model_file_that_a_version_points_to_is_kept(db: AsyncSession) -> None:
    store = MemoryStore()
    _, key = await a_model_file(db, store)
    result = await collector(db, store).collect(dry_run=False)
    assert key in store.objects
    assert (result.scanned, result.garbage_objects) == (1, 0)


async def test_an_old_model_file_that_nothing_points_to_is_deleted(db: AsyncSession) -> None:
    store = MemoryStore()
    model, kept = await a_model_file(db, store)
    orphan = litter(store, f"models/{model.id}/files/{uuid.uuid4()}")
    result = await collector(db, store).collect(dry_run=False)
    assert orphan not in store.objects and kept in store.objects
    assert result.deleted_objects == 1


async def test_a_young_model_file_is_kept_even_if_nothing_points_to_it(db: AsyncSession) -> None:
    store = MemoryStore()
    key = litter(store, f"models/{uuid.uuid4()}/files/{uuid.uuid4()}", old=False)
    await collector(db, store).collect(dry_run=False)
    assert key in store.objects


async def test_a_file_that_an_open_model_upload_points_to_is_kept_until_the_upload_is_over(db: AsyncSession) -> None:
    store = MemoryStore()
    model, _ = await a_model_file(db, store)
    upload = ModelUpload(
        id=uuid.uuid4(),
        model_id=model.id,
        created_by="u1",
        created_by_username="ada",
        expires_at=model.created_at + timedelta(days=1),
    )
    db.add(upload)
    await db.flush()
    key = litter(store, f"models/{model.id}/files/waiting-for-its-row")
    db.add(
        ModelUploadFile(
            id=uuid.uuid4(),
            upload_id=upload.id,
            path="b.bin",
            size_bytes=1,
            content_type="application/octet-stream",
            storage_key=key,
            part_size=5 * 1024**2,
            parts_count=1,
        )
    )
    await db.commit()
    await collector(db, store).collect(dry_run=False)
    assert key in store.objects
    await db.execute(update(ModelUpload).values(status="expired"))
    await db.commit()
    await collector(db, store).collect(dry_run=False)
    assert key not in store.objects


async def test_a_model_upload_in_parts_that_something_owns_is_not_given_up(db: AsyncSession) -> None:
    store = MemoryStore()
    model, _ = await a_model_file(db, store)
    owned = await store.create_multipart(f"models/{model.id}/files/owned", "application/octet-stream")
    stray = await store.create_multipart(f"models/{model.id}/files/stray", "application/octet-stream")
    for upload_id in (owned, stray):
        store.uploads[upload_id]["initiated"] = datetime.now(UTC) - OLD
    upload = ModelUpload(
        id=uuid.uuid4(),
        model_id=model.id,
        created_by="u1",
        created_by_username="ada",
        expires_at=model.created_at + timedelta(days=1),
    )
    db.add(upload)
    await db.flush()
    db.add(
        ModelUploadFile(
            id=uuid.uuid4(),
            upload_id=upload.id,
            path="o.bin",
            size_bytes=1,
            content_type="application/octet-stream",
            storage_key=f"models/{model.id}/files/owned",
            multipart_id=owned,
            part_size=5 * 1024**2,
            parts_count=1,
        )
    )
    await db.commit()
    result = await collector(db, store).collect(dry_run=False)
    assert result.started_uploads_given_up == 1
    assert owned in store.uploads and stray not in store.uploads


async def test_a_model_file_that_is_missing_from_the_storage_is_told(db: AsyncSession) -> None:
    store = MemoryStore()
    _, key = await a_model_file(db, store)
    del store.objects[key]
    result = await collector(db, store).collect(dry_run=False)
    assert result.missing_objects == 1 and result.missing_keys == [key]
