"""The fingerprints of the files of a model, computed by the worker and checked by the API."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app
from app.models import ModelFile, ModelVersion
from app.routers.deps import get_jobs
from tests.conftest import MemoryRegistry, MemoryStore
from tests.routers.test_model_versions import ADDRESS, WEIGHTS, announce, push, send_parts, start

KEY = "worker-key-of-sixteen-characters"
HEADERS = {"X-Api-Key": KEY}
BASE = "/api/internal/model-versions"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RecordedJobs:
    def __init__(self) -> None:
        self.model_versions: list[uuid.UUID] = []
        self.codes: list[uuid.UUID] = []

    async def process_version(self, version_id: uuid.UUID) -> None:
        return None

    async def convert_file(self, derivative_id: uuid.UUID) -> None:
        return None

    async def process_model_version(self, version_id: uuid.UUID) -> None:
        self.model_versions.append(version_id)

    async def resolve_code(self, version_id: uuid.UUID) -> None:
        self.codes.append(version_id)


@pytest.fixture(autouse=True)
def _setup(registry: MemoryRegistry, monkeypatch: pytest.MonkeyPatch) -> MemoryRegistry:
    monkeypatch.setattr(settings, "WORKER_API_KEY", KEY)
    return registry


@pytest.fixture
def jobs():
    recorded = RecordedJobs()
    app.dependency_overrides[get_jobs] = lambda: recorded
    yield recorded
    app.dependency_overrides.pop(get_jobs, None)


async def version_id(db: AsyncSession, number: int = 1) -> uuid.UUID:
    return (await db.execute(select(ModelVersion.id).where(ModelVersion.number == number))).scalar_one()


async def check(
    client: httpx2.AsyncClient, store: MemoryStore, vid: uuid.UUID, corrupt: dict[str, bytes] | None = None
):
    """What the worker does: claims the version, reads each file at its address, says what it found."""
    claim = (await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)).json()
    if not claim["claimed"]:
        return None
    found = []
    for file in claim["files"]:
        data = store.objects[file["url"].removeprefix("memory://get/")].data
        data = (corrupt or {}).get(file["path"], data)
        found.append({"id": file["id"], "size_bytes": len(data), "sha256": sha(data)})
    return (await client.post(f"{BASE}/{vid}/result", headers=HEADERS, json={"files": found})).json()["status"]


async def test_the_worker_is_queued_when_a_version_has_files_to_check(client, login, store, jobs, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    assert jobs.model_versions == [await version_id(db)]


async def test_a_version_of_code_only_has_nothing_to_check(client, login, jobs) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": {"url": "https://github.com/ada/sentiment"}})
    assert jobs.model_versions == []


async def test_the_fingerprints_are_written_and_the_version_is_ready(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS, "config.json": b"{}"})
    assert await check(client, store, await version_id(db)) == "ready"
    files = {f.path: f.sha256 for f in (await db.execute(select(ModelFile))).scalars()}
    assert files == {"weights.bin": sha(WEIGHTS), "config.json": sha(b"{}")}
    assert (await client.get(f"{ADDRESS}/versions/1")).json()["status"] == "ready"


async def test_a_second_worker_gets_nothing(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    assert (await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)).json()["claimed"] is True
    assert (await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)).json()["claimed"] is False


async def test_a_version_that_is_ready_is_not_claimed(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    await check(client, store, vid)
    assert (await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)).json()["claimed"] is False


async def test_a_file_that_is_not_the_one_announced_fails_the_version_and_is_named(client, login, store, db) -> None:
    await start(client, login)
    announced = {"path": "weights.bin", "size": len(WEIGHTS), "sha256": sha(WEIGHTS)}
    upload = (await client.post(f"{ADDRESS}/uploads", json={"files": [announced]})).json()
    other = b"x" * len(WEIGHTS)  # the same size, not the same content
    await send_parts(client, store, upload, {"weights.bin": other})
    assert (await client.post(f"/api/model-uploads/{upload['id']}/complete")).status_code == 200
    vid = await version_id(db)
    assert await check(client, store, vid) == "failed"
    version = (await client.get(f"{ADDRESS}/versions/1")).json()
    assert version["status"] == "failed" and "weights.bin" in version["error"] and sha(WEIGHTS) in version["error"]
    assert (await db.execute(select(ModelFile.sha256))).scalar_one() is None  # nothing of it was kept
    assert (await client.get(f"{ADDRESS}/files/weights.bin")).status_code == 409  # and it is not given


async def test_a_file_of_another_size_than_announced_fails_the_version(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    claim = (await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)).json()
    body = {"files": [{"id": claim["files"][0]["id"], "size_bytes": 3, "sha256": sha(b"abc")}]}
    assert (await client.post(f"{BASE}/{vid}/result", headers=HEADERS, json=body)).json()["status"] == "failed"
    assert "weights.bin" in (await client.get(f"{ADDRESS}/versions/1")).json()["error"]


async def test_a_file_the_worker_did_not_read_fails_the_version(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)
    assert (await client.post(f"{BASE}/{vid}/result", headers=HEADERS, json={"files": []})).json()["status"] == "failed"


async def test_a_failure_of_the_worker_is_recorded(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)
    answer = await client.post(f"{BASE}/{vid}/failure", headers=HEADERS, json={"error": "weights.bin is missing"})
    assert answer.json()["status"] == "failed"
    assert (await client.get(f"{ADDRESS}/versions/1")).json()["error"] == "weights.bin is missing"


async def test_a_version_that_failed_can_be_checked_again(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)
    await client.post(f"{BASE}/{vid}/failure", headers=HEADERS, json={"error": "x"})
    assert await check(client, store, vid) == "ready"
    assert (await client.get(f"{ADDRESS}/versions/1")).json()["error"] is None


async def test_a_release_gives_the_version_back(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)
    assert (await client.post(f"{BASE}/{vid}/release", headers=HEADERS)).json()["status"] == "pending"
    assert (await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)).json()["claimed"] is True


async def test_a_result_for_a_version_nobody_holds_is_refused(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    assert (await client.post(f"{BASE}/{vid}/result", headers=HEADERS, json={"files": []})).status_code == 409
    assert (await client.post(f"{BASE}/{uuid.uuid4()}/result", headers=HEADERS, json={"files": []})).status_code == 404


async def test_a_version_checked_too_many_times_is_given_up(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    await db.execute(update(ModelVersion).values(attempts=settings.PROCESSING_MAX_ATTEMPTS))
    await db.commit()
    assert (await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)).json()["claimed"] is False
    version = (await client.get(f"{ADDRESS}/versions/1")).json()
    assert version["status"] == "failed" and "too many" in version["error"]


async def test_a_worker_that_died_is_replaced(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    await client.post(f"{BASE}/{vid}/claim", headers=HEADERS)
    old = datetime.now(UTC) - timedelta(minutes=settings.PROCESSING_STALE_MINUTES + 1)
    await db.execute(update(ModelVersion).values(processing_started_at=old))
    await db.commit()
    assert vid in [uuid.UUID(i) for i in (await client.get(f"{BASE}/waiting", headers=HEADERS)).json()["ids"]]
    assert await check(client, store, vid) == "ready"


async def test_the_sweep_finds_the_versions_that_wait(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    assert (await client.get(f"{BASE}/waiting", headers=HEADERS)).json()["ids"] == []  # too young
    await db.execute(update(ModelVersion).values(created_at=datetime.now(UTC) - timedelta(minutes=10)))
    await db.commit()
    assert (await client.get(f"{BASE}/waiting", headers=HEADERS)).json()["ids"] == [str(vid)]


async def test_the_same_content_sent_again_is_stored_once(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    await check(client, store, await version_id(db, 1))
    await push(client, store, **{"copy.bin": WEIGHTS})  # the same bytes under another name, sent again
    assert len([k for k in store.objects if k.startswith("models/")]) == 2
    assert await check(client, store, await version_id(db, 2)) == "ready"
    keys = {f.path: f.storage_key for f in (await db.execute(select(ModelFile))).scalars()}
    assert keys["copy.bin"] == keys["weights.bin"]
    assert len([k for k in store.objects if k.startswith("models/")]) == 1  # the duplicate object is gone
    assert (
        await client.get(f"{ADDRESS}/files/copy.bin", params={"version": 2}, follow_redirects=False)
    ).status_code == 302


async def test_once_fingerprinted_a_file_is_not_sent_again(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    await check(client, store, await version_id(db))
    upload = (
        await client.post(
            f"{ADDRESS}/uploads", json={"files": [{"path": "more.bin", "size": len(WEIGHTS), "sha256": sha(WEIGHTS)}]}
        )
    ).json()
    assert upload["files"][0]["already_stored"] is True
    done = await client.post(f"/api/model-uploads/{upload['id']}/complete")
    assert done.json()["status"] == "ready"  # nothing to check: the content is known


async def test_a_new_version_that_only_keeps_files_waits_for_the_ones_still_unknown(
    client, login, store, jobs, db
) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})  # not fingerprinted yet
    second = await client.post(f"{ADDRESS}/versions", json={"code": {"url": "https://github.com/ada/sentiment"}})
    assert second.json()["status"] == "pending"  # the file it keeps has to be read
    assert len(jobs.model_versions) == 2  # and the check is queued for it too


async def test_only_the_worker_may_call(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    vid = await version_id(db)
    for method, path in (
        ("POST", f"{BASE}/{vid}/claim"),
        ("GET", f"{BASE}/waiting"),
        ("POST", f"{BASE}/{vid}/release"),
    ):
        assert (await client.request(method, path)).status_code == 401
        assert (await client.request(method, path, headers={"X-Api-Key": "x" * 32})).status_code == 401
    login("u9", "root", admin=True)
    assert (await client.post(f"{BASE}/{vid}/claim")).status_code == 401


async def test_the_expiry_job_also_gives_up_the_uploads_of_models(client, login, store, db) -> None:
    await start(client, login)
    upload = (await announce(client, ("weights.bin", len(WEIGHTS)))).json()
    await send_parts(client, store, upload, {"weights.bin": WEIGHTS})
    from app.models import ModelUpload

    await db.execute(update(ModelUpload).values(expires_at=datetime.now(UTC) - timedelta(hours=1)))
    await db.commit()
    answer = await client.post("/api/internal/dataset-uploads/expire", headers=HEADERS)
    assert answer.json() == {"expired": 1}
