"""The code of a version: checked when it is written, pinned to a commit by the worker, and never changed after."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app
from app.models import ModelVersion
from app.routers.deps import get_jobs
from app.services.code_reference import parse_repository, tree_url
from app.services.errors import InvalidCodeReference
from tests.conftest import MemoryRegistry
from tests.routers.test_model_checks import RecordedJobs
from tests.routers.test_model_versions import ADDRESS, start

KEY = "worker-key-of-sixteen-characters"
HEADERS = {"X-Api-Key": KEY}
BASE = "/api/internal/model-versions"
SHA = "a" * 40
CODE = {"url": "https://github.com/ada/sentiment", "ref": "v1.0", "path": "src", "entrypoint": "src/predict.py"}
HOSTS = ["github.com", "gitlab.com", "git.example.org:8443"]


@pytest.fixture(autouse=True)
def _setup(registry: MemoryRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WORKER_API_KEY", KEY)


@pytest.fixture
def jobs():
    recorded = RecordedJobs()
    app.dependency_overrides[get_jobs] = lambda: recorded
    yield recorded
    app.dependency_overrides.pop(get_jobs, None)


async def the_version(db: AsyncSession) -> uuid.UUID:
    return (await db.execute(select(ModelVersion.id).order_by(ModelVersion.number.desc()).limit(1))).scalar_one()


async def state(db: AsyncSession, version_id: uuid.UUID) -> ModelVersion:
    await db.rollback()
    return (await db.execute(select(ModelVersion).where(ModelVersion.id == version_id))).scalar_one()


# ---- the address of a repository


@pytest.mark.parametrize(
    ("url", "host", "project"),
    [
        ("https://github.com/ada/sentiment", "github.com", "ada/sentiment"),
        ("https://GitHub.com/ada/sentiment.git", "github.com", "ada/sentiment"),
        ("https://github.com/ada/sentiment/", "github.com", "ada/sentiment"),
        ("https://github.com/ada/.github", "github.com", "ada/.github"),
        ("https://gitlab.com/ada/sentiment", "gitlab.com", "ada/sentiment"),
        ("https://gitlab.com/group/sub/sub2/project", "gitlab.com", "group/sub/sub2/project"),  # groups in groups
        ("https://git.example.org:8443/team/model", "git.example.org", "team/model"),  # the port of its entry
    ],
)
def test_a_repository_of_an_allowed_host_is_accepted(url: str, host: str, project: str) -> None:
    repository = parse_repository(url, HOSTS)
    assert (repository.host, repository.project) == (host, project)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/ada/x",
        "https://user@github.com/ada/x",
        "https://user:pw@github.com/ada/x",
        "https://github.com@evil.example/ada/x",
        "https://evil.example@github.com/ada/x",
        "https://127.0.0.1/ada/x",
        "https://[::1]/ada/x",
        "https://localhost/ada/x",
        "https://0x7f.0.0.1/ada/x",
        "https://2130706433/ada/x",
        "https://github.com./ada/x",  # a trailing dot is another name
        "https://github.com:444/ada/x",  # a port that is not the one of the entry
        "https://github.com:8443/ada/x",
        "https://git.example.org/team/model",  # the entry says 8443: 443 is not allowed there
        "https://git.example.org:443/team/model",
        "https://git.example.org:9999/team/model",
        "https://gitlab.com:8443/ada/x",
        "https://evil.example/ada/x",
        "https://github.com.evil.example/ada/x",
        "https://xgithub.com/ada/x",
        "https://github.com/ada",  # not a repository
        "https://github.com/",
        "https://github.com/ada/x/tree/main",  # GitHub has no groups in groups
        "https://gitlab.com/ada/x/-/tree/main",  # a GitLab page, not the repository
        "https://gitlab.com/ada/-/x",
        "https://gitlab.com/a/b/c/d/e/f/g",  # too deep
        "https://github.com/ada//x",
        "https://github.com/ada/../x",
        "https://github.com/ada/./x",
        "https://github.com/%2e%2e/x",
        "https://github.com/ada/x%2Fy",
        "https://github.com/ada/x?a=b",
        "https://github.com/ada/x#y",
        "https://github.com/ada/x y",
        "https://github.com/ada/é",
        "https:///ada/x",
        "//github.com/ada/x",
        "github.com/ada/x",
        "javascript:alert(1)",
        "",
    ],
)
def test_what_is_not_the_repository_of_an_allowed_host_is_refused(url: str) -> None:
    with pytest.raises(InvalidCodeReference):
        parse_repository(url, HOSTS)


def test_the_page_of_the_exact_commit_is_built_from_the_checked_parts() -> None:
    assert tree_url("https://github.com/ada/x.git", SHA, "src/m", HOSTS) == f"https://github.com/ada/x/tree/{SHA}/src/m"
    assert tree_url("https://gitlab.com/g/s/x", SHA, None, HOSTS) == f"https://gitlab.com/g/s/x/-/tree/{SHA}"
    assert tree_url("https://git.example.org:8443/t/m", SHA, "a b", HOSTS) == (
        f"https://git.example.org:8443/t/m/-/tree/{SHA}/a%20b"
    )
    assert tree_url("https://evil.example/t/m", SHA, None, HOSTS) is None  # not an allowed host (any more)


# ---- the job and what the version shows


async def test_a_version_with_code_queues_the_pinning(client, login, jobs, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    assert jobs.codes == [await the_version(db)]


async def test_a_version_without_code_queues_nothing(client, login, jobs) -> None:
    await start(client, login)
    assert (await client.post(f"{ADDRESS}/versions", json={"message": "x"})).status_code == 422
    assert jobs.codes == []


async def test_a_reference_is_shown_as_not_pinned_until_it_is_and_then_as_the_commit(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    code = (await client.get(f"{ADDRESS}/versions/1")).json()["code"]
    assert (code["ref"], code["sha"], code["state"], code["tree_url"]) == ("v1.0", None, "unresolved", None)
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    await client.post(f"{BASE}/{vid}/code/pinned", headers=HEADERS, json={"sha": SHA})
    code = (await client.get(f"{ADDRESS}/versions/1")).json()["code"]
    assert (code["ref"], code["sha"], code["state"]) == ("v1.0", SHA, "pinned")  # what was written is still there
    assert code["tree_url"] == f"https://github.com/ada/sentiment/tree/{SHA}/src"


# ---- the worker


async def test_the_worker_claims_the_code_and_gets_what_to_look_for(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    answer = (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json()
    assert answer == {"claimed": True, "url": CODE["url"], "ref": "v1.0", "ref_kind": "unknown"}
    assert (await state(db, vid)).code_state == "resolving"
    assert (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json() == {
        "claimed": False,
        "url": None,
        "ref": None,
        "ref_kind": None,
    }


async def test_no_reference_means_the_default_branch(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": {"url": "https://github.com/ada/sentiment"}})
    vid = await the_version(db)
    answer = (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json()
    assert answer["claimed"] is True and answer["ref"] is None


async def test_a_pinned_commit_is_never_changed(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    assert (await client.post(f"{BASE}/{vid}/code/pinned", headers=HEADERS, json={"sha": SHA})).json() == {
        "state": "pinned"
    }
    # nobody can take it again, and nothing can be written on it
    assert (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json()["claimed"] is False
    other = "b" * 40
    assert (await client.post(f"{BASE}/{vid}/code/pinned", headers=HEADERS, json={"sha": other})).status_code == 409
    assert (
        await client.post(f"{BASE}/{vid}/code/unverified", headers=HEADERS, json={"reason": "x"})
    ).status_code == 409
    assert (await client.post(f"{BASE}/{vid}/code/failure", headers=HEADERS, json={"reason": "x"})).status_code == 409
    await client.post(f"{BASE}/{vid}/code/release", headers=HEADERS)
    assert (await state(db, vid)).code_sha == SHA and (await state(db, vid)).code_state == "pinned"


async def test_a_commit_is_not_written_by_somebody_who_did_not_take_the_code(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    assert (await client.post(f"{BASE}/{vid}/code/pinned", headers=HEADERS, json={"sha": SHA})).status_code == 409
    assert (
        await client.post(f"{BASE}/{uuid.uuid4()}/code/pinned", headers=HEADERS, json={"sha": SHA})
    ).status_code == 404


@pytest.mark.parametrize("sha", ["", "abc", "A" * 40, "g" * 40, "a" * 41, "a" * 39, "a" * 64 + "a", "main"])
async def test_what_is_not_a_commit_is_refused(client, login, db, sha: str) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    assert (await client.post(f"{BASE}/{vid}/code/pinned", headers=HEADERS, json={"sha": sha})).status_code == 422
    assert (await state(db, vid)).code_state == "resolving"


async def test_a_sha_256_commit_is_accepted(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    assert (await client.post(f"{BASE}/{vid}/code/pinned", headers=HEADERS, json={"sha": "c" * 64})).status_code == 200


async def test_a_repository_that_is_not_found_is_not_verified_and_the_version_is_not_failed(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    answer = await client.post(
        f"{BASE}/{vid}/code/unverified", headers=HEADERS, json={"reason": "not found or private"}
    )
    assert answer.json() == {"state": "unverified"}
    version = (await client.get(f"{ADDRESS}/versions/1")).json()
    assert version["code"]["state"] == "unverified" and version["code"]["error"] == "not found or private"
    assert version["code"]["url"] == CODE["url"] and version["code"]["sha"] is None  # kept as written
    assert version["status"] == "ready"  # the version itself is fine
    assert (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json()["claimed"] is False


async def test_an_answer_that_cannot_be_used_fails_the_code_with_the_reason(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    await client.post(f"{BASE}/{vid}/code/failure", headers=HEADERS, json={"reason": "GitHub answered 418"})
    code = (await client.get(f"{ADDRESS}/versions/1")).json()["code"]
    assert (code["state"], code["error"]) == ("failed", "GitHub answered 418")


async def test_a_release_gives_the_code_back(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    assert (await client.post(f"{BASE}/{vid}/code/release", headers=HEADERS)).json() == {"state": "unresolved"}
    assert (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json()["claimed"] is True


async def test_code_taken_too_many_times_is_given_up(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    await db.execute(update(ModelVersion).values(code_attempts=settings.PROCESSING_MAX_ATTEMPTS))
    await db.commit()
    assert (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json()["claimed"] is False
    code = (await client.get(f"{ADDRESS}/versions/1")).json()["code"]
    assert code["state"] == "failed" and "too many" in code["error"]


async def test_a_worker_that_died_is_replaced_and_the_sweep_finds_the_code(client, login, db) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    waiting = "/api/internal/model-code/waiting"
    assert (await client.get(waiting, headers=HEADERS)).json()["ids"] == []  # too young
    await db.execute(update(ModelVersion).values(created_at=datetime.now(UTC) - timedelta(minutes=10)))
    await db.commit()
    assert (await client.get(waiting, headers=HEADERS)).json()["ids"] == [str(vid)]
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    assert (await client.get(waiting, headers=HEADERS)).json()["ids"] == []  # somebody has it
    old = datetime.now(UTC) - timedelta(minutes=settings.PROCESSING_STALE_MINUTES + 1)
    await db.execute(update(ModelVersion).values(code_started_at=old))
    await db.commit()
    assert (await client.get(waiting, headers=HEADERS)).json()["ids"] == [str(vid)]
    assert (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json()["claimed"] is True


async def test_a_host_that_is_not_allowed_any_more_is_not_looked_up(client, login, db, monkeypatch) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    monkeypatch.setattr(settings, "MODEL_CODE_HOSTS", ["gitlab.com"])
    assert (await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)).json()["claimed"] is False
    assert (await client.get(f"{ADDRESS}/versions/1")).json()["code"]["state"] == "failed"


async def test_the_files_and_the_code_of_a_version_are_two_jobs(client, login, db) -> None:
    """Taking the code in hand does not touch the check of the files, and the other way round."""
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    vid = await the_version(db)
    await client.post(f"{BASE}/{vid}/code/claim", headers=HEADERS)
    version = await state(db, vid)
    assert (version.attempts, version.processing_started_at, version.code_attempts) == (0, None, 1)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/internal/model-versions/{id}/code/claim"),
        ("POST", "/api/internal/model-versions/{id}/code/pinned"),
        ("POST", "/api/internal/model-versions/{id}/code/unverified"),
        ("POST", "/api/internal/model-versions/{id}/code/failure"),
        ("POST", "/api/internal/model-versions/{id}/code/release"),
        ("GET", "/api/internal/model-code/waiting"),
    ],
)
async def test_only_the_worker_may_call(client, login, db, method: str, path: str) -> None:
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})
    path = path.format(id=await the_version(db))
    assert (await client.request(method, path)).status_code == 401
    assert (await client.request(method, path, headers={"X-Api-Key": "x" * 32})).status_code == 401
    login("u9", "root", admin=True)
    assert (await client.request(method, path)).status_code == 401
