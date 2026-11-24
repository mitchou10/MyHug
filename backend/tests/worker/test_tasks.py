import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DatasetVersion
from app.services.dataset_versions import NamedUpload
from app.worker import tasks
from app.worker.jobs import CeleryJobs
from tests.conftest import MemoryStore
from tests.services.test_dataset_processing import CSV, setup
from tests.services.test_dataset_services import ADA


@pytest.fixture
def worker_store(monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
    """The storage the tasks use: the tasks build their own, as a worker does."""
    memory = MemoryStore()
    monkeypatch.setattr(tasks, "get_store", lambda: memory)
    return memory


async def test_the_task_reads_the_version_in_its_own_session(db: AsyncSession, worker_store: MemoryStore) -> None:
    version = await setup(db, worker_store, ("train.csv", CSV))
    # A worker has no event loop of its own running: the task makes one.
    assert await asyncio.to_thread(tasks.process_version.apply, args=[str(version.id)]) is not None
    await db.refresh(version)
    assert (version.status, version.rows) == ("ready", 3)


async def test_the_task_of_a_version_that_does_not_exist_ends_quietly(worker_store: MemoryStore) -> None:
    result = await asyncio.to_thread(tasks.process_version.apply, args=[str(uuid.uuid4())])
    assert result.successful() and result.result is None


async def test_the_sweep_queues_the_versions_that_wait(
    db: AsyncSession, worker_store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = await setup(db, worker_store, ("train.csv", CSV))
    await db.execute(update(DatasetVersion).values(created_at=datetime.now(UTC) - timedelta(hours=1)))
    await db.commit()
    queued: list[list[str]] = []
    monkeypatch.setattr(tasks.process_version, "apply_async", lambda args: queued.append(args))
    assert await asyncio.to_thread(tasks.process_waiting) == 1
    assert queued == [[str(version.id)]]


async def test_the_job_that_expires_the_uploads_runs(worker_store: MemoryStore) -> None:
    assert await asyncio.to_thread(tasks.expire_uploads) == 0


async def test_a_version_is_queued_when_it_is_made(db: AsyncSession) -> None:
    queued: list[uuid.UUID] = []

    class Recorder:
        async def process_version(self, version_id: uuid.UUID) -> None:
            queued.append(version_id)

    from app.services.factory import build_dataset_versions

    store = MemoryStore()
    await setup(db, store, ("a.csv", CSV))  # makes the dataset
    version = await build_dataset_versions(db, store, Recorder()).create(
        ADA, "ada", "reviews", uploads=[NamedUpload(path="b.csv", data=CSV)], remove=[], message=""
    )
    assert queued == [version.id]


async def test_a_queue_that_is_down_does_not_fail_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_, **__):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(tasks.process_version, "apply_async", broken)
    await CeleryJobs().process_version(uuid.uuid4())  # no error: the sweep will find the version


def test_the_schedule_names_tasks_that_exist() -> None:
    from app.worker.celery_app import celery_app

    names = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert names <= set(celery_app.tasks)
