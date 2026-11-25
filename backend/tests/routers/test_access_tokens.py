"""Access tokens: a program acting as a person. The requests here go through the real authentication: `login` is only
used to be the person who makes the token, then it is dropped and the token is all the program has."""

import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.deps import get_current_user
from app.config import settings
from app.main import app
from app.models import AccessToken
from app.serving import MemoryRateLimiter, get_rate_limiter
from tests.routers.test_models import create, share

TOKENS = "/api/tokens"


@pytest.fixture(autouse=True)
def limiter() -> Iterator[MemoryRateLimiter]:
    memory = MemoryRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: memory
    yield memory
    app.dependency_overrides.pop(get_rate_limiter, None)


async def make(client: httpx2.AsyncClient, name: str = "laptop", scope: str = "write", **fields) -> dict:
    """Makes a token as the logged-in person (the call must succeed)."""
    response = await client.post(TOKENS, json={"name": name, "scope": scope, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def program(login: Callable[..., RequestContext]) -> Callable[[], None]:
    """From now on nobody is logged in: only the tokens the program sends count."""

    def _drop() -> None:
        app.dependency_overrides.pop(get_current_user, None)

    return _drop


# ---- making, listing, revoking: for a person who is logged in


async def test_a_token_is_shown_once_and_never_again(client, login, db: AsyncSession) -> None:
    login("u1", "ada")
    created = await make(client, name="training job", scope="read", expires_in_days=30)
    secret = created["token"]
    assert secret.startswith("mh_") and len(secret) > 40
    assert created["prefix"] == secret[:11]
    assert created["scope"] == "read" and created["expires_at"] and created["last_used_at"] is None

    listed = (await client.get(TOKENS)).json()
    assert [t["name"] for t in listed] == ["training job"]
    assert "token" not in listed[0]
    assert secret not in (await client.get(TOKENS)).text

    # Only a fingerprint is kept: the database cannot give the token back.
    row = (await db.execute(select(AccessToken))).scalar_one()
    assert secret not in {row.token_hash, row.prefix, row.name, row.username}
    assert len(row.token_hash) == 64


async def test_two_tokens_are_never_the_same(client, login) -> None:
    login("u1", "ada")
    assert (await make(client, "a"))["token"] != (await make(client, "b"))["token"]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "scope": "read"},
        {"name": "   ", "scope": "read"},
        {"name": "x" * 101, "scope": "read"},
        {"name": "x", "scope": "admin"},
        {"name": "x", "scope": "read", "expires_in_days": 0},
        {"name": "x", "scope": "read", "expires_in_days": 366},
    ],
)
async def test_what_is_not_valid_is_refused(client, login, body: dict) -> None:
    login("u1", "ada")
    assert (await client.post(TOKENS, json=body)).status_code == 422


async def test_the_list_is_mine_only(client, login) -> None:
    login("u1", "ada")
    await make(client, "mine")
    login("u2", "bob")
    await make(client, "his")
    assert [t["name"] for t in (await client.get(TOKENS)).json()] == ["his"]


async def test_a_token_is_revoked_by_its_owner_only_and_doing_it_again_changes_nothing(client, login) -> None:
    login("u1", "ada")
    token = await make(client)
    login("u2", "bob")
    assert (await client.delete(f"{TOKENS}/{token['id']}")).status_code == 404  # it looks like it does not exist
    login("u1", "ada")
    assert (await client.delete(f"{TOKENS}/{token['id']}")).status_code == 204
    assert (await client.delete(f"{TOKENS}/{token['id']}")).status_code == 204
    assert (await client.get(TOKENS)).json()[0]["revoked_at"]


async def test_the_tokens_of_a_person_are_limited(client, login, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TOKENS_MAX_ACTIVE", 2)
    login("u1", "ada")
    first = await make(client, "one")
    await make(client, "two")
    assert (await client.post(TOKENS, json={"name": "three", "scope": "read"})).status_code == 409
    await client.delete(f"{TOKENS}/{first['id']}")  # a revoked one does not count
    assert (await client.post(TOKENS, json={"name": "three", "scope": "read"})).status_code == 201


async def test_nothing_is_made_without_a_login(client) -> None:
    assert (await client.get(TOKENS)).status_code == 401
    assert (await client.post(TOKENS, json={"name": "x", "scope": "read"})).status_code == 401


# ---- a program with a token


async def test_a_token_acts_as_its_owner(client, login, program) -> None:
    login("u1", "ada")
    token = await make(client)
    await create(client, "private-one", visibility="private")
    program()
    seen = await client.get("/api/models/ada/private-one", headers=bearer(token["token"]))
    assert seen.status_code == 200 and seen.json()["can_edit"] is True
    made = await client.post(
        "/api/models",
        json={"name": "from-a-script", "tasks": ["classification"], "inputs": ["text"]},
        headers=bearer(token["token"]),
    )
    assert made.status_code == 201
    assert made.json()["owner"] == "ada"  # in the name of the person, not of the token


async def test_a_token_gives_no_access_to_what_its_owner_cannot_see(client, login, program) -> None:
    login("u1", "ada")
    await create(client, "hers", visibility="private")
    login("u2", "bob")
    token = await make(client)
    program()
    assert (await client.get("/api/models/ada/hers", headers=bearer(token["token"]))).status_code == 404
    listed = (await client.get("/api/models", headers=bearer(token["token"]))).json()
    assert listed["total"] == 0


async def test_taking_the_owner_off_a_model_takes_the_token_off_it_at_once(client, login, program, db) -> None:
    login("u1", "ada")
    await create(client, "shared-one", visibility="private")
    await share(db, "ada/shared-one", "u2", "reader")
    login("u2", "bob")
    token = await make(client)
    program()
    headers = bearer(token["token"])
    assert (await client.get("/api/models/ada/shared-one", headers=headers)).status_code == 200
    await db.execute(text("DELETE FROM model_members"))
    await db.commit()
    assert (await client.get("/api/models/ada/shared-one", headers=headers)).status_code == 404


async def test_a_read_token_reads_and_cannot_change_anything(client, login, program) -> None:
    login("u1", "ada")
    token = await make(client, scope="read")
    await create(client, "sentiment")
    program()
    headers = bearer(token["token"])
    assert (await client.get("/api/models/ada/sentiment", headers=headers)).status_code == 200
    body = {"name": "other", "tasks": ["classification"], "inputs": ["text"]}
    assert (await client.post("/api/models", json=body, headers=headers)).status_code == 403
    assert (
        await client.patch("/api/models/ada/sentiment", json={"license": "mit"}, headers=headers)
    ).status_code == 403
    assert (await client.put("/api/models/ada/sentiment/like", headers=headers)).status_code == 403
    assert (await client.delete("/api/models/ada/sentiment", headers=headers)).status_code == 403
    assert "read only" in (await client.delete("/api/models/ada/sentiment", headers=headers)).json()["detail"]
    assert (await client.get("/api/models/ada/sentiment", headers=headers)).status_code == 200  # still there


async def test_a_read_token_may_still_try_a_model(client, login, program) -> None:
    """Trying a model is a POST that changes nothing: it is not refused as a write."""
    login("u1", "ada")
    token = await make(client, scope="read")
    await create(client, "sentiment")
    program()
    answer = await client.post(
        "/api/models/ada/sentiment/predict", json={"input": "hi"}, headers=bearer(token["token"])
    )
    assert answer.status_code == 409  # got past the token: the model is simply not served


async def test_a_write_token_changes_things(client, login, program) -> None:
    login("u1", "ada")
    token = await make(client, scope="write")
    await create(client, "sentiment")
    program()
    headers = bearer(token["token"])
    assert (
        await client.patch("/api/models/ada/sentiment", json={"license": "mit"}, headers=headers)
    ).status_code == 200
    assert (await client.delete("/api/models/ada/sentiment", headers=headers)).status_code == 204


async def test_a_token_is_never_an_administrator_even_when_its_owner_is(client, login, program) -> None:
    login("u1", "root", admin=True)
    assert (await client.get("/api/admin/feedback")).status_code == 200  # the person is
    token = await make(client, scope="write")
    program()
    headers = bearer(token["token"])
    assert (await client.get("/api/admin/feedback", headers=headers)).status_code == 403
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 403  # and a token does not even say who it is: that needs a login


async def test_a_token_cannot_manage_tokens_nor_the_profile(client, login, program) -> None:
    login("u1", "ada")
    token = await make(client, scope="write")
    program()
    headers = bearer(token["token"])
    assert (await client.get(TOKENS, headers=headers)).status_code == 403
    assert (await client.post(TOKENS, json={"name": "x", "scope": "read"}, headers=headers)).status_code == 403
    assert (await client.delete(f"{TOKENS}/{token['id']}", headers=headers)).status_code == 403
    assert (await client.get("/api/me/profile", headers=headers)).status_code == 403
    assert (await client.delete("/api/me/avatar", headers=headers)).status_code == 403
    login("u1", "ada")  # nothing was changed: the token still works for what it may do
    assert (await client.get(TOKENS)).json()[0]["revoked_at"] is None


# ---- what is refused


async def test_a_token_that_is_wrong_revoked_or_expired_is_refused_the_same_way(client, login, program, db) -> None:
    login("u1", "ada")
    revoked = await make(client, "revoked")
    expired = await make(client, "expired")
    await client.delete(f"{TOKENS}/{revoked['id']}")
    await db.execute(
        update(AccessToken)
        .where(AccessToken.name == "expired")
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db.commit()
    program()
    answers = [
        await client.get("/api/models", headers=bearer(token))
        for token in (revoked["token"], expired["token"], "mh_nothing", "mh_")
    ]
    assert [a.status_code for a in answers] == [401, 401, 401, 401]
    assert len({a.text for a in answers}) == 1  # nothing tells which of the three it was


async def test_a_wrong_token_is_not_rescued_by_a_session(client, login, program) -> None:
    program()
    assert (await client.get("/api/models", headers=bearer("mh_wrong"))).status_code == 401


async def test_the_calls_of_a_token_are_limited(client, login, program, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TOKEN_RATE_PER_MINUTE", 2)
    login("u1", "ada")
    token = await make(client)
    other = await make(client, "other")
    program()
    codes = [(await client.get("/api/models", headers=bearer(token["token"]))).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert (await client.get("/api/models", headers=bearer(other["token"]))).status_code == 200  # its own count


# ---- what is recorded


async def test_a_token_says_when_it_was_last_used_without_writing_at_every_call(client, login, program, db) -> None:
    login("u1", "ada")
    token = await make(client)
    program()
    assert (await db.execute(select(AccessToken.last_used_at))).scalar_one() is None
    await client.get("/api/models", headers=bearer(token["token"]))
    first = (await db.execute(select(AccessToken.last_used_at))).scalar_one()
    assert first is not None
    await client.get("/api/models", headers=bearer(token["token"]))
    assert (await db.execute(select(AccessToken.last_used_at))).scalar_one() == first  # less than a minute: not written
    await db.execute(update(AccessToken).values(last_used_at=first - timedelta(minutes=5)))
    await db.commit()
    await client.get("/api/models", headers=bearer(token["token"]))
    assert (await db.execute(select(AccessToken.last_used_at))).scalar_one() > first - timedelta(minutes=1)


async def test_each_call_leaves_one_line_with_the_token_id_and_never_the_token(
    client, login, program, caplog: pytest.LogCaptureFixture
) -> None:
    login("u1", "ada")
    token = await make(client)
    program()
    with caplog.at_level(logging.INFO, logger="app.tokens"):
        await client.get("/api/models", headers=bearer(token["token"]))
        await client.get("/api/models/ada/nothing", headers=bearer(token["token"]))
    lines = [r.getMessage() for r in caplog.records if r.name == "app.tokens"]
    assert lines == [
        f"token={token['id']} GET /api/models -> 200",
        f"token={token['id']} GET /api/models/ada/nothing -> 404",
    ]
    assert token["token"] not in caplog.text


async def test_the_token_is_in_no_other_answer(client, login, program) -> None:
    login("u1", "ada")
    token = await make(client)
    await create(client, "sentiment")
    program()
    for path in ("/api/models", "/api/models/ada/sentiment"):
        assert token["token"] not in (await client.get(path, headers=bearer(token["token"]))).text
    login("u1", "ada")
    assert token["token"] not in (await client.get(TOKENS)).text


async def test_a_call_without_a_token_leaves_no_line(client, login, caplog: pytest.LogCaptureFixture) -> None:
    login("u1", "ada")
    with caplog.at_level(logging.INFO, logger="app.tokens"):
        await client.get("/api/models")
    assert not [r for r in caplog.records if r.name == "app.tokens"]
