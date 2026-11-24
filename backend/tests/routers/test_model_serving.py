"""Trying a model: it is served only where an editor says so, and the relay never gives away where."""

import json
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app
from app.models import ModelEndpoint
from app.serving import MemoryRateLimiter, ServingClient, get_rate_limiter, get_serving_client
from tests.routers.test_models import MODELS, create, share

ADDRESS = f"{MODELS}/ada/sentiment-fr"
ORIGIN = "http://mlflow-serving:5001"
MLFLOW = {
    "kind": "mlflow",
    "url": f"{ORIGIN}/sentiment",
    "alias": "production",
    "input_kind": "text",
    "output_kind": "labels",
}
CUSTOM: dict[str, Any] = {
    "kind": "custom",
    "url": "https://models.example.org/v1",
    "input_kind": "text",
    "output_kind": "labels",
    "api": {"path": "/classify", "input_field": "text", "output_path": "result.0.label"},
}


class Server:
    """The servers of the models, as the relay meets them: answers in turn, and the requests they got."""

    def __init__(self) -> None:
        self.answers: list[httpx2.Response | Exception] = []
        self.requests: list[httpx2.Request] = []
        self.ping = httpx2.Response(200, text="\n")

    def say(self, *answers: httpx2.Response | Exception) -> "Server":
        self.answers.extend(answers)
        return self

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path.endswith("/ping"):
            return self.ping
        answer = self.answers.pop(0) if self.answers else httpx2.Response(200, json={"predictions": ["ok"]})
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def last(self) -> httpx2.Request:
        return self.requests[-1]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fake = Server()
    monkeypatch.setattr(settings, "MODEL_SERVING_ORIGINS", [ORIGIN, "https://models.example.org"])

    def client() -> ServingClient:
        return ServingClient(
            origins=settings.MODEL_SERVING_ORIGINS,
            timeout=5,
            max_response_bytes=settings.SERVING_MAX_RESPONSE_BYTES,
            transport=httpx2.MockTransport(fake),
        )

    limiter = MemoryRateLimiter()
    app.dependency_overrides[get_serving_client] = client
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    yield fake
    app.dependency_overrides.pop(get_serving_client, None)
    app.dependency_overrides.pop(get_rate_limiter, None)


async def start(client, login, **fields) -> None:
    login("u1", "ada")
    await create(client, **fields)


async def serve(client, body: dict = MLFLOW) -> httpx2.Response:
    return await client.put(f"{ADDRESS}/endpoint", json=body)


def predict(client, value="great film", **extra):
    return client.post(f"{ADDRESS}/predict", json={"input": value, **extra})


# ---- served only when somebody says where


async def test_a_model_without_an_endpoint_cannot_be_tried(client, login, server) -> None:
    await start(client, login)
    assert (await predict(client)).status_code == 409
    assert server.requests == []
    assert (await client.get(ADDRESS)).json()["serving"] is None


async def test_an_editor_declares_an_mlflow_server_that_answers(client, login, server) -> None:
    await start(client, login)
    response = await serve(client)
    assert response.status_code == 200, response.text
    endpoint = response.json()
    assert (endpoint["kind"], endpoint["url"], endpoint["alias"], endpoint["available"]) == (
        "mlflow",
        f"{ORIGIN}/sentiment",
        "production",
        True,
    )
    assert server.requests[0].url.path == "/sentiment/ping"  # it was asked before it was believed


async def test_an_mlflow_server_that_does_not_answer_is_not_declared(client, login, server) -> None:
    await start(client, login)
    server.ping = httpx2.Response(503)
    assert (await serve(client)).status_code == 503
    assert (await client.get(f"{ADDRESS}/endpoint")).status_code == 409  # nothing was saved
    assert (await predict(client)).status_code == 409


async def test_a_server_that_goes_down_is_seen_by_the_editors(client, login, server) -> None:
    await start(client, login)
    await serve(client)
    server.ping = httpx2.Response(500)
    assert (await client.get(f"{ADDRESS}/endpoint")).json()["available"] is False


async def test_a_service_of_your_own_is_declared_with_its_api(client, login, server) -> None:
    await start(client, login)
    response = await serve(client, CUSTOM)
    assert response.status_code == 200, response.text
    assert response.json()["api"] == {"path": "/classify", "input_field": "text", "output_path": "result.0.label"}
    assert response.json()["available"] is None  # nothing is known of its API: it is not asked
    assert server.requests == []


async def test_the_api_of_a_service_of_your_own_is_needed_and_an_mlflow_one_has_none(client, login, server) -> None:
    await start(client, login)
    assert (await serve(client, {**CUSTOM, "api": None})).status_code == 422
    assert (await serve(client, {**MLFLOW, "api": CUSTOM["api"]})).status_code == 422


async def test_the_endpoint_is_replaced_and_removed(client, login, server) -> None:
    await start(client, login)
    await serve(client)
    assert (await serve(client, CUSTOM)).json()["kind"] == "custom"
    assert (await client.delete(f"{ADDRESS}/endpoint")).status_code == 204
    assert (await predict(client)).status_code == 409
    assert (await client.delete(f"{ADDRESS}/endpoint")).status_code == 409


# ---- what an editor may make the backend call


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://localhost:5001/x",
        "http://127.0.0.1:5001",
        "http://mlflow-serving:5002/x",  # another port
        "https://mlflow-serving:5001/x",  # another scheme
        "http://mlflow-serving.evil.example:5001",
        "http://mlflow-serving:5001@evil.example/x",
        "http://user:pw@mlflow-serving:5001/x",
        "http://evil.example@mlflow-serving:5001/x",
        "http://mlflow-serving:5001/../admin",
        "http://mlflow-serving:5001//x",
        "http://mlflow-serving:5001/x?token=1",
        "http://mlflow-serving:5001/x#f",
        "http://mlflow-serving:5001/x y",
        "ftp://mlflow-serving:5001/x",
        "file:///etc/passwd",
        "mlflow-serving:5001",
        "//mlflow-serving:5001/x",
        "",
    ],
)
async def test_an_address_that_is_not_on_the_allowlist_is_refused(client, login, server, url: str) -> None:
    await start(client, login)
    assert (await serve(client, {**MLFLOW, "url": url})).status_code == 422
    assert server.requests == []  # nothing was called


async def test_nothing_is_served_where_nothing_is_allowed(client, login, server, monkeypatch) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "MODEL_SERVING_ORIGINS", [])
    assert (await serve(client)).status_code == 422


async def test_an_address_that_was_allowed_is_checked_again_at_every_call(client, login, server, monkeypatch) -> None:
    await start(client, login)
    await serve(client)
    monkeypatch.setattr(settings, "MODEL_SERVING_ORIGINS", ["https://models.example.org"])
    requests = len(server.requests)
    assert (await predict(client)).status_code == 422
    assert len(server.requests) == requests


@pytest.mark.parametrize(
    "api",
    [
        {"path": "classify"},
        {"path": "/../admin"},
        {"path": "/x?a=1"},
        {"path": "//evil.example/x"},
        {"path": "/x#f"},
        {"input_field": "a b"},
        {"input_field": ""},
        {"output_path": "a..b"},
        {"output_path": "a/b"},
    ],
)
async def test_the_api_of_a_service_must_be_plain(client, login, server, api: dict) -> None:
    await start(client, login)
    assert (await serve(client, {**CUSTOM, "api": {**CUSTOM["api"], **api}})).status_code == 422


@pytest.mark.parametrize("header", ["Host", "Content-Length", "Transfer-Encoding", "X-Forwarded-For", "a b", "a:b", ""])
async def test_a_header_that_would_change_where_the_request_goes_is_refused(client, login, server, header) -> None:
    await start(client, login)
    body = {**CUSTOM, "auth_header": header, "auth_value": "secret"}
    assert (await serve(client, body)).status_code == 422


# ---- the relay


async def test_an_input_goes_to_an_mlflow_server_and_its_predictions_come_back(client, login, server) -> None:
    await start(client, login)
    await serve(client)
    server.say(httpx2.Response(200, json={"predictions": [{"label": "pos", "score": 0.9}]}))
    response = await predict(client, ["great film"])
    assert response.status_code == 200, response.text
    assert response.json()["output"] == [{"label": "pos", "score": 0.9}]
    assert isinstance(response.json()["took_ms"], int)
    assert server.last.method == "POST" and server.last.url.path == "/sentiment/invocations"
    assert json.loads(server.last.content) == {"inputs": ["great film"]}


async def test_an_input_goes_to_a_service_of_your_own_with_the_field_it_names(client, login, server) -> None:
    await start(client, login)
    await serve(client, CUSTOM)
    server.say(httpx2.Response(200, json={"result": [{"label": "pos"}]}))
    response = await predict(client, "great film")
    assert response.json()["output"] == "pos"  # what is at `result.0.label`
    assert str(server.last.url) == "https://models.example.org/v1/classify"
    assert json.loads(server.last.content) == {"text": "great film"}


async def test_an_answer_without_the_output_that_was_described_is_an_error_of_the_server(client, login, server) -> None:
    await start(client, login)
    await serve(client, CUSTOM)
    server.say(httpx2.Response(200, json={"other": 1}))
    assert (await predict(client)).status_code == 502


async def test_the_login_of_a_service_goes_to_it_and_is_never_given_back(client, login, server) -> None:
    await start(client, login)
    body = {**CUSTOM, "auth_header": "X-Api-Key", "auth_value": "s3cret-value"}
    saved = await serve(client, body)
    assert saved.json()["auth_header"] == "X-Api-Key" and saved.json()["has_auth"] is True
    await predict(client)
    assert server.last.headers["x-api-key"] == "s3cret-value"
    for response in (saved, await client.get(f"{ADDRESS}/endpoint"), await client.get(ADDRESS)):
        assert "s3cret-value" not in response.text
    # sending the header alone keeps the value; another header without a value is refused
    assert (await serve(client, {**CUSTOM, "auth_header": "X-Api-Key"})).json()["has_auth"] is True
    await predict(client)
    assert server.last.headers["x-api-key"] == "s3cret-value"
    assert (await serve(client, {**CUSTOM, "auth_header": "Authorization"})).status_code == 422


async def test_a_value_without_its_header_is_refused(client, login, server) -> None:
    await start(client, login)
    assert (await serve(client, {**CUSTOM, "auth_value": "x"})).status_code == 422


async def test_a_server_that_is_down_is_a_503(client, login, server) -> None:
    await start(client, login)
    await serve(client)
    server.say(httpx2.ConnectError("refused"))
    assert (await predict(client)).status_code == 503
    server.say(httpx2.Response(502))
    assert (await predict(client)).status_code == 503


async def test_a_server_that_is_too_slow_is_a_504(client, login, server) -> None:
    await start(client, login)
    await serve(client)
    server.say(httpx2.ReadTimeout("slow"))
    assert (await predict(client)).status_code == 504


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 404, 429, 500])
async def test_nothing_else_the_server_says_is_passed_on(client, login, server, status: int) -> None:
    await start(client, login)
    await serve(client)
    server.say(
        httpx2.Response(status, headers={"location": "http://169.254.169.254/"}, text="internal detail 10.0.0.7")
    )
    response = await predict(client)
    assert response.status_code == 503
    assert "10.0.0.7" not in response.text and "169.254" not in response.text
    assert [r.method for r in server.requests].count("POST") == 1  # a redirect is never followed
    assert {r.url.host for r in server.requests} == {"mlflow-serving"}


@pytest.mark.parametrize("status", [400, 415, 422])
async def test_an_input_the_model_refuses_is_a_422(client, login, server, status: int) -> None:
    await start(client, login)
    await serve(client)
    server.say(httpx2.Response(status, text="column 'x' is missing at /srv/model.py"))
    response = await predict(client)
    assert response.status_code == 422 and "/srv" not in response.text


async def test_an_answer_that_is_not_json_or_too_large_is_an_error_of_the_server(
    client, login, server, monkeypatch
) -> None:
    await start(client, login)
    await serve(client)
    server.say(httpx2.Response(200, text="<html>"))
    assert (await predict(client)).status_code == 502
    monkeypatch.setattr(settings, "SERVING_MAX_RESPONSE_BYTES", 100)
    server.say(httpx2.Response(200, json={"predictions": "x" * 500}))
    assert (await predict(client)).status_code == 502


async def test_an_input_that_is_too_large_is_refused_before_it_is_sent(client, login, server, monkeypatch) -> None:
    await start(client, login)
    await serve(client)
    monkeypatch.setattr(settings, "SERVING_MAX_BODY_BYTES", 1000)
    requests = len(server.requests)
    assert (await predict(client, "x" * 5000)).status_code == 413
    assert len(server.requests) == requests
    assert (await predict(client, "x" * 100)).status_code == 200


async def test_the_size_is_checked_on_what_is_received_not_on_what_is_declared(
    client, login, server, monkeypatch
) -> None:
    await start(client, login)
    await serve(client)
    monkeypatch.setattr(settings, "SERVING_MAX_BODY_BYTES", 1000)

    async def body():
        yield b'{"input": "'
        for _ in range(10):
            yield b"x" * 500  # no length is declared: it is a stream
        yield b'"}'

    assert (await client.post(f"{ADDRESS}/predict", content=body())).status_code == 413


@pytest.mark.parametrize("body", [b"", b"nope", b"[]", b'{"other": 1}', b'"text"'])
async def test_a_body_that_is_not_an_input_is_refused(client, login, server, body: bytes) -> None:
    await start(client, login)
    await serve(client)
    response = await client.post(f"{ADDRESS}/predict", content=body)
    assert response.status_code == 422


async def test_each_person_has_a_rate_limit(client, login, server, monkeypatch) -> None:
    await start(client, login)
    await serve(client)
    monkeypatch.setattr(settings, "SERVING_RATE_PER_MINUTE", 3)
    assert [(await predict(client)).status_code for _ in range(4)] == [200, 200, 200, 429]
    login("u2", "bob")  # somebody else is not held back
    assert (await predict(client)).status_code == 200


# ---- who may do what


async def test_a_reader_tries_the_model_and_never_learns_where(client, login, server, db) -> None:
    await start(client, login, visibility="private")
    await serve(client)
    await share(db, "ada/sentiment-fr", "u2", "reader")
    login("u2", "bob")
    assert (await predict(client)).status_code == 200
    model = await client.get(ADDRESS)
    assert model.json()["serving"] == {"kind": "mlflow", "input": "text", "output": "labels"}
    for response in (model, await client.get(MODELS), await client.get(f"{ADDRESS}/versions")):
        assert (
            "mlflow-serving" not in response.text and "5001" not in response.text and "/sentiment" not in response.text
        )
    assert (await client.get(f"{ADDRESS}/endpoint")).status_code == 403
    assert (await serve(client)).status_code == 403
    assert (await client.delete(f"{ADDRESS}/endpoint")).status_code == 403


async def test_the_address_is_in_no_answer_to_anyone_but_the_editors(client, login, server, db) -> None:
    await start(client, login)
    await serve(client, {**MLFLOW, "alias": "production"})
    await share(db, "ada/sentiment-fr", "u2", "reader")
    await share(db, "ada/sentiment-fr", "u3", "maintainer")
    login("u3", "carol")
    assert (await client.get(f"{ADDRESS}/endpoint")).json()["url"] == f"{ORIGIN}/sentiment"  # a maintainer
    for user in ("u2", "u4"):  # a reader, a stranger
        login(user, "someone")
        for response in (await client.get(ADDRESS), await client.get(MODELS), await predict(client)):
            assert ORIGIN not in response.text and "mlflow-serving" not in response.text


async def test_a_private_model_cannot_be_tried_by_a_stranger(client, login, server) -> None:
    await start(client, login, visibility="private")
    await serve(client)
    login("u2", "bob")
    assert (await predict(client)).status_code == 404
    assert (await client.get(f"{ADDRESS}/endpoint")).status_code == 404
    assert (await serve(client)).status_code == 404


async def test_nobody_logged_out_tries_a_model(client, login, server) -> None:
    await start(client, login)
    await serve(client)
    from app.auth.deps import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    assert (await predict(client)).status_code == 401
    assert (await client.get(f"{ADDRESS}/endpoint")).status_code == 401


async def test_deleting_a_model_removes_its_endpoint(client, login, server, db: AsyncSession) -> None:
    await start(client, login)
    await serve(client, {**CUSTOM, "auth_header": "X-Api-Key", "auth_value": "s3cret"})
    await client.delete(ADDRESS)
    assert (await db.execute(select(ModelEndpoint))).first() is None
