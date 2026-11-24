import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.config import settings
from app.models import DatasetVersion
from tests.conftest import MemoryStore
from tests.services.test_dataset_processing import CSV, setup

KEY = "worker-key-of-sixteen-characters"
HEADERS = {"X-Api-Key": KEY}
BASE = "/api/internal"


@pytest.fixture(autouse=True)
def worker_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WORKER_API_KEY", KEY)


async def test_the_worker_is_known_by_its_key(client: httpx2.AsyncClient) -> None:
    assert (await client.get(f"{BASE}/dataset-versions/waiting")).status_code == 401
    assert (await client.get(f"{BASE}/dataset-versions/waiting", headers={"X-Api-Key": "x" * 32})).status_code == 401
    assert (await client.get(f"{BASE}/dataset-versions/waiting", headers=HEADERS)).status_code == 200


async def test_without_a_key_configured_nobody_gets_in(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "WORKER_API_KEY", "")
    assert (await client.get(f"{BASE}/dataset-versions/waiting", headers={"X-Api-Key": ""})).status_code == 401
    monkeypatch.setattr(settings, "WORKER_API_KEY", "short")
    assert (await client.get(f"{BASE}/dataset-versions/waiting", headers={"X-Api-Key": "short"})).status_code == 401


async def test_a_user_cannot_use_the_worker_routes(client: httpx2.AsyncClient, login) -> None:
    login("u1", "ada", admin=True)
    assert (await client.post(f"{BASE}/dataset-uploads/expire")).status_code == 401


async def test_the_worker_claims_a_version_and_gets_what_to_read(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    version = await setup(db, store, ("train.csv", CSV), ("README.md", b"# x"))
    answer = (await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)).json()
    assert answer["claimed"] is True
    (file,) = answer["files"]  # the README holds no rows and already has its fingerprint
    assert (file["path"], file["needs_rows"], file["needs_fingerprint"]) == ("train.csv", True, False)
    assert file["url"].startswith("memory://get/")
    # Taken: a second worker gets nothing.
    assert (await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)).json()[
        "claimed"
    ] is False


async def test_the_result_of_the_worker_makes_the_version_ready(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    version = await setup(db, store, ("train.csv", CSV))
    (file,) = (await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)).json()["files"]
    body = {
        "files": [{"id": file["id"], "size_bytes": len(CSV), "rows": 3, "columns": [{"name": "n", "dtype": "int"}]}]
    }
    answer = await client.post(f"{BASE}/dataset-versions/{version.id}/result", json=body, headers=HEADERS)
    assert (answer.status_code, answer.json()) == (200, {"status": "ready"})
    await db.refresh(version)
    assert (version.rows, version.columns) == (3, [{"name": "n", "dtype": "int"}])


async def test_a_result_for_a_version_that_is_not_held_is_refused(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    version = await setup(db, store, ("train.csv", CSV))
    body = {"files": []}
    assert (
        await client.post(f"{BASE}/dataset-versions/{version.id}/result", json=body, headers=HEADERS)
    ).status_code == 409
    missing = uuid.uuid4()
    assert (
        await client.post(f"{BASE}/dataset-versions/{missing}/result", json=body, headers=HEADERS)
    ).status_code == 404


async def test_a_size_that_is_not_the_announced_one_fails_the_version(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    version = await setup(db, store, ("train.csv", CSV))
    (file,) = (await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)).json()["files"]
    body = {"files": [{"id": file["id"], "size_bytes": 1, "rows": 3, "columns": []}]}
    answer = await client.post(f"{BASE}/dataset-versions/{version.id}/result", json=body, headers=HEADERS)
    assert answer.json() == {"status": "failed"}
    await db.refresh(version)
    assert "train.csv" in (version.error or "")


async def test_a_file_that_was_not_reported_fails_the_version(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    version = await setup(db, store, ("train.csv", CSV))
    await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)
    answer = await client.post(f"{BASE}/dataset-versions/{version.id}/result", json={"files": []}, headers=HEADERS)
    assert answer.json() == {"status": "failed"}


async def test_the_worker_can_say_that_a_file_cannot_be_read(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    version = await setup(db, store, ("train.csv", CSV))
    await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)
    answer = await client.post(
        f"{BASE}/dataset-versions/{version.id}/failure", json={"error": "train.csv is not a csv"}, headers=HEADERS
    )
    assert answer.json() == {"status": "failed"}
    await db.refresh(version)
    assert version.error == "train.csv is not a csv"
    # A version that failed is taken again when somebody asks.
    assert (await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)).json()["claimed"] is True


async def test_a_released_version_waits_again(client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore) -> None:
    version = await setup(db, store, ("train.csv", CSV))
    await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)
    await client.post(f"{BASE}/dataset-versions/{version.id}/release", headers=HEADERS)
    await db.refresh(version)
    assert version.status == "pending"


async def test_a_version_that_keeps_being_interrupted_ends_failed(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    version = await setup(db, store, ("train.csv", CSV))
    await db.execute(update(DatasetVersion).values(attempts=3))
    await db.commit()
    assert (await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)).json()[
        "claimed"
    ] is False
    await db.refresh(version)
    assert version.status == "failed" and "interrupted" in (version.error or "")


async def test_a_version_whose_worker_died_is_taken_again_after_a_while(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    version = await setup(db, store, ("train.csv", CSV))
    await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)
    assert (await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)).json()[
        "claimed"
    ] is False
    await db.execute(update(DatasetVersion).values(processing_started_at=datetime.now(UTC) - timedelta(hours=1)))
    await db.commit()
    assert (await client.post(f"{BASE}/dataset-versions/{version.id}/claim", headers=HEADERS)).json()["claimed"] is True


async def test_the_sweep_lists_the_versions_nobody_is_reading(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore
) -> None:
    old = await setup(db, store, ("a.csv", CSV))
    await setup(db, store, ("b.csv", b"n\n5\n"))  # too recent: its job is probably about to start
    await db.execute(
        update(DatasetVersion)
        .where(DatasetVersion.id == old.id)
        .values(created_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db.commit()
    assert (await client.get(f"{BASE}/dataset-versions/waiting", headers=HEADERS)).json() == {"ids": [str(old.id)]}


async def test_the_job_that_expires_the_uploads_runs(client: httpx2.AsyncClient) -> None:
    answer = await client.post(f"{BASE}/dataset-uploads/expire", headers=HEADERS)
    assert (answer.status_code, answer.json()) == (200, {"expired": 0})


# ---- the queue: the API puts a job in Redis by the name of the task


async def test_a_job_is_queued_by_the_name_of_the_task(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple] = []

    class Fake:
        def send_task(self, name: str, **options) -> None:
            sent.append((name, options))

    queue = jobs.CeleryJobs()
    monkeypatch.setattr(queue, "_celery", lambda: Fake())
    version_id = uuid.uuid4()
    await queue.process_version(version_id)
    assert sent == [("datasets.process_version", {"args": [str(version_id)], "queue": "datasets"})]


async def test_a_queue_that_is_down_does_not_fail_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class Down:
        def send_task(self, *_, **__) -> None:
            raise ConnectionError("redis is down")

    queue = jobs.CeleryJobs()
    monkeypatch.setattr(queue, "_celery", lambda: Down())
    await queue.process_version(uuid.uuid4())  # no error: the sweep will find the version


async def test_the_client_of_the_queue_is_built_once() -> None:
    queue = jobs.CeleryJobs()
    assert queue._celery() is queue._celery()  # noqa: SLF001
    assert queue._celery().conf.broker_url == settings.REDIS_URL  # noqa: SLF001
