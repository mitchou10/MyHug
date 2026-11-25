"""The collector and the predictions of the evaluations: it must know what points to them."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Model, ModelEvaluation, ModelVersion
from tests.conftest import MemoryStore
from tests.services.test_storage_garbage import collector, litter


async def an_evaluation(
    db: AsyncSession, store: MemoryStore, *, uploading: bool = False
) -> tuple[ModelEvaluation, str]:
    model = Model(id=uuid.uuid4(), owner="ada", name="m", created_by="u1", created_by_username="ada")
    db.add(model)
    await db.flush()
    version = ModelVersion(id=uuid.uuid4(), model_id=model.id, number=1, created_by="u1", created_by_username="ada")
    db.add(version)
    await db.flush()
    evaluation_id = uuid.uuid4()
    key = litter(store, f"evaluations/{evaluation_id}/predictions.jsonl", data=b'{"prediction": 1}\n')
    evaluation = ModelEvaluation(
        id=evaluation_id,
        model_id=model.id,
        version_id=version.id,
        version_number=1,
        task="classification",
        source="predictions",
        status="uploading" if uploading else "pending",
        predictions_key=key,
        predictions_format="jsonl",
        predictions_size=18,
        multipart_id="upload-1" if uploading else None,
        expires_at=datetime.now(UTC) + timedelta(days=1) if uploading else None,
        created_by="u1",
        created_by_username="ada",
    )
    db.add(evaluation)
    await db.commit()
    return evaluation, key


async def test_predictions_that_an_evaluation_points_to_are_kept(db: AsyncSession) -> None:
    store = MemoryStore()
    _, key = await an_evaluation(db, store)
    result = await collector(db, store).collect(dry_run=False)
    assert key in store.objects and (result.scanned, result.garbage_objects) == (1, 0)


async def test_predictions_that_nothing_points_to_are_deleted(db: AsyncSession) -> None:
    store = MemoryStore()
    _, kept = await an_evaluation(db, store)
    orphan = litter(store, f"evaluations/{uuid.uuid4()}/predictions.csv")
    result = await collector(db, store).collect(dry_run=False)
    assert orphan not in store.objects and kept in store.objects and result.deleted_objects == 1


async def test_predictions_of_a_deleted_evaluation_are_collected(db: AsyncSession) -> None:
    store = MemoryStore()
    evaluation, key = await an_evaluation(db, store)
    await db.delete(evaluation)
    await db.commit()
    await collector(db, store).collect(dry_run=False)
    assert key not in store.objects


async def test_an_upload_that_an_evaluation_owns_is_not_given_up(db: AsyncSession) -> None:
    store = MemoryStore()
    _, key = await an_evaluation(db, store, uploading=True)
    store.uploads["upload-1"] = {
        "key": key,
        "content_type": "x",
        "parts": {},
        "initiated": datetime.now(UTC) - timedelta(days=30),
    }
    result = await collector(db, store).collect(dry_run=False)
    assert "upload-1" in store.uploads and result.started_uploads_given_up == 0


async def test_an_upload_that_nothing_owns_is_given_up(db: AsyncSession) -> None:
    store = MemoryStore()
    key = f"evaluations/{uuid.uuid4()}/predictions.jsonl"
    store.uploads["lost"] = {
        "key": key,
        "content_type": "x",
        "parts": {},
        "initiated": datetime.now(UTC) - timedelta(days=30),
    }
    result = await collector(db, store).collect(dry_run=False)
    assert "lost" not in store.uploads and result.started_uploads_given_up == 1
