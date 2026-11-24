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


# ---- the copies of the files in Parquet


async def a_copy(db: AsyncSession, store: MemoryStore, monkeypatch: pytest.MonkeyPatch):
    from sqlalchemy import select

    from app.models import DatasetFileDerivative
    from tests.reading import Reader

    monkeypatch.setattr(settings, "DERIVATIVE_MIN_BYTES", 0)
    version = await setup(db, store, ("train.csv", CSV))
    await Reader(db, store).process(version.id)
    return (await db.execute(select(DatasetFileDerivative))).scalar_one()


async def test_the_worker_makes_a_copy_through_the_routes(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    copy = await a_copy(db, store, monkeypatch)
    base = f"{BASE}/derivatives/{copy.id}"
    claimed = (await client.post(f"{base}/claim", headers=HEADERS)).json()
    assert claimed["claimed"] is True and claimed["source_path"] == "train.csv"
    assert claimed["source_url"].startswith("memory://get/") and claimed["part_bytes"] > 0
    assert (await client.post(f"{base}/claim", headers=HEADERS)).json() == {
        "claimed": False,
        "id": None,
        "source_url": None,
        "source_path": None,
        "source_size_bytes": None,
        "part_bytes": None,
    }

    parts = (await client.post(f"{base}/parts", json={"numbers": [1]}, headers=HEADERS)).json()["parts"]
    sink = io.BytesIO()
    pq.write_table(pa.table({"n": [1, 2, 3]}), sink)
    store.receive(parts[0]["url"], sink.getvalue())
    body = {"rows": 3, "columns": [{"name": "n", "dtype": "int"}]}
    assert (await client.post(f"{base}/result", json=body, headers=HEADERS)).json() == {"status": "ready"}
    await db.refresh(copy)
    assert (copy.status, copy.rows, copy.size_bytes) == ("ready", 3, len(sink.getvalue()))


async def test_the_routes_of_the_copies_need_the_key(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = await a_copy(db, store, monkeypatch)
    for method, path in (
        ("POST", "claim"),
        ("POST", "parts"),
        ("POST", "result"),
        ("POST", "failure"),
        ("GET", "waiting"),
    ):
        target = f"{BASE}/derivatives/{path if path == 'waiting' else f'{copy.id}/{path}'}"
        assert (await client.request(method, target)).status_code == 401


async def test_a_copy_that_is_not_held_is_refused_and_one_that_does_not_exist_is_not_found(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = await a_copy(db, store, monkeypatch)
    body = {"rows": 1, "columns": []}
    assert (await client.post(f"{BASE}/derivatives/{copy.id}/result", json=body, headers=HEADERS)).status_code == 409
    assert (
        await client.post(f"{BASE}/derivatives/{uuid.uuid4()}/failure", json={"error": "x"}, headers=HEADERS)
    ).status_code == 404


async def test_the_worker_can_say_that_a_copy_cannot_be_made_or_give_it_back(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = await a_copy(db, store, monkeypatch)
    base = f"{BASE}/derivatives/{copy.id}"
    await client.post(f"{base}/claim", headers=HEADERS)
    assert (await client.post(f"{base}/release", headers=HEADERS)).status_code == 200
    await db.refresh(copy)
    assert copy.status == "pending"
    await client.post(f"{base}/claim", headers=HEADERS)
    failed = await client.post(f"{base}/failure", json={"error": "not a csv"}, headers=HEADERS)
    assert failed.json() == {"status": "failed"}
    await db.refresh(copy)
    assert copy.error == "not a csv"


async def test_the_sweep_lists_the_copies_nobody_is_making(
    client: httpx2.AsyncClient, db: AsyncSession, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import DatasetFileDerivative

    copy = await a_copy(db, store, monkeypatch)
    assert (await client.get(f"{BASE}/derivatives/waiting", headers=HEADERS)).json() == {"ids": []}  # too recent
    await db.execute(update(DatasetFileDerivative).values(created_at=datetime.now(UTC) - timedelta(hours=1)))
    await db.commit()
    assert (await client.get(f"{BASE}/derivatives/waiting", headers=HEADERS)).json() == {"ids": [str(copy.id)]}


async def test_a_copy_is_queued_by_the_name_of_the_task(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple] = []

    class Fake:
        def send_task(self, name: str, **options) -> None:
            sent.append((name, options))

    queue = jobs.CeleryJobs()
    monkeypatch.setattr(queue, "_celery", lambda: Fake())
    derivative = uuid.uuid4()
    await queue.convert_file(derivative)
    assert sent == [("datasets.convert_file", {"args": [str(derivative)], "queue": "datasets"})]


# ---- the objects of the storage that nothing points to


def an_old_orphan(store: MemoryStore) -> str:
    key = "datasets/d1/orphan"
    store.objects[key] = MemoryStore.stored(b"x", "application/octet-stream")
    store.age(key, timedelta(days=30))
    return key


async def test_the_collection_needs_the_key(client: httpx2.AsyncClient) -> None:
    assert (await client.post(f"{BASE}/storage/collect", json={})).status_code == 401


async def test_the_collection_starts_as_a_dry_run_and_deletes_nothing(
    client: httpx2.AsyncClient, store: MemoryStore
) -> None:
    key = an_old_orphan(store)
    answer = (await client.post(f"{BASE}/storage/collect", json={}, headers=HEADERS)).json()
    assert answer["enabled"] is True and answer["dry_run"] is True
    assert (answer["garbage_objects"], answer["deleted_objects"], answer["next_after"]) == (1, 0, None)
    assert key in store.objects


async def test_the_collection_deletes_once_the_dry_run_is_turned_off(
    client: httpx2.AsyncClient, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "STORAGE_GC_DRY_RUN", False)
    key = an_old_orphan(store)
    careful = (await client.post(f"{BASE}/storage/collect", json={"dry_run": True}, headers=HEADERS)).json()
    assert careful["dry_run"] is True and key in store.objects  # a request can be more careful than the setting
    done = (await client.post(f"{BASE}/storage/collect", json={"dry_run": False}, headers=HEADERS)).json()
    assert (done["dry_run"], done["deleted_objects"]) == (False, 1) and key not in store.objects


async def test_a_request_cannot_turn_off_the_dry_run_of_the_setting(
    client: httpx2.AsyncClient, store: MemoryStore
) -> None:
    key = an_old_orphan(store)
    answer = (await client.post(f"{BASE}/storage/collect", json={"dry_run": False}, headers=HEADERS)).json()
    assert answer["dry_run"] is True and key in store.objects


async def test_the_collection_can_be_switched_off(
    client: httpx2.AsyncClient, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "STORAGE_GC_ENABLED", False)
    monkeypatch.setattr(settings, "STORAGE_GC_DRY_RUN", False)
    key = an_old_orphan(store)
    answer = (await client.post(f"{BASE}/storage/collect", json={}, headers=HEADERS)).json()
    assert answer["enabled"] is False and key in store.objects
