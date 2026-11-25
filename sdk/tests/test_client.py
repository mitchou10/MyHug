import httpx2
import pytest

from myhug import AsyncClient, Client, errors
from myhug._retry import Retry
from tests.fake import API, FakePlatform


def item(name: str) -> dict:
    return {
        "id": "00000000-0000-0000-0000-000000000001", "owner": "ada", "name": name, "description": "",
        "modality": "text",
        "language": "", "license": "", "tags": [], "visibility": "public", "downloads": 0, "likes": 0, "liked": False,
        "version": 1, "rows": 3, "size_bytes": 10, "created_by": "u1", "created_by_username": "ada",
        "created_at": "2026-11-01T09:00:00Z", "updated_at": "2026-11-01T09:00:00Z",
    }  # fmt: skip


# ---- the token


def test_the_token_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch, platform: FakePlatform) -> None:
    monkeypatch.setenv("MYHUG_URL", API)
    monkeypatch.setenv("MYHUG_TOKEN", "mh_good")
    with Client(transport=httpx2.MockTransport(platform)) as client:
        assert client.json("GET", "/api/datasets", params={"limit": 1, "offset": 0})["total"] == 0


def test_the_token_is_in_no_repr_and_no_error(platform: FakePlatform) -> None:
    client = Client(API, token="mh_secret", transport=httpx2.MockTransport(platform))
    assert "mh_secret" not in repr(client) and "mh_secret" not in str(vars(client).get("url"))
    with pytest.raises(errors.AuthenticationError) as raised:
        client.json("GET", "/api/datasets", params={"limit": 1, "offset": 0})
    assert "mh_secret" not in str(raised.value) and "mh_secret" not in repr(raised.value)


def test_a_token_does_not_travel_over_plain_http_except_to_this_machine() -> None:
    with pytest.raises(errors.InsecureUrl):
        Client("http://myhug.example", token="mh_x")
    Client("http://localhost:8000", token="mh_x").close()
    Client("http://127.0.0.1:8000", token="mh_x").close()
    Client("http://myhug.example", token="mh_x", allow_insecure=True).close()
    Client("http://myhug.example").close()  # no token, nothing to leak


@pytest.mark.parametrize("url", ["ftp://x", "not a url", "https://ada:pw@myhug.example", ""])
def test_a_wrong_address_is_refused(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYHUG_URL", raising=False)
    if url == "":
        Client(url, token=None).close()  # falls back on the default address
        return
    with pytest.raises(errors.MyHugError):
        Client(url, token="mh_x")


async def test_the_token_goes_to_the_api_and_never_to_the_storage(driver, platform: FakePlatform) -> None:
    platform.files["a.bin"] = b"abcd"
    from myhug._download import adownload, download

    await driver.call(
        download if driver.mode == "sync" else adownload, "/api/files/a.bin", driver.client.cache_dir / "out.bin"
    )
    storage = [r for r in platform.requests if r.url.host == "storage.test"]
    assert storage and all("authorization" not in r.headers for r in storage)
    assert all(r.headers["authorization"] == "Bearer mh_good" for r in platform.api_calls())


# ---- errors


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, errors.AuthenticationError),
        (403, errors.PermissionDenied),
        (404, errors.NotFound),
        (409, errors.Conflict),
        (413, errors.TooLarge),
        (422, errors.Invalid),
        (400, errors.ApiError),
        (500, errors.ServerError),
    ],
)
async def test_each_status_is_its_own_exception_with_the_sentence_of_the_api(build, platform, status, kind) -> None:
    for mode in ("sync", "async"):
        d = build(mode, retry=Retry(attempts=0))
        platform.say("GET", "/api/x", httpx2.Response(status, json={"detail": "A sentence."}))
        with pytest.raises(kind) as raised:
            await d.json("GET", "/api/x")
        assert raised.value.status_code == status and raised.value.detail == "A sentence."
        assert isinstance(raised.value, errors.ApiError)


async def test_the_problems_of_a_wrong_request_are_listed_short(build, platform) -> None:
    d = build("sync", retry=Retry(attempts=0))
    detail = [{"loc": ["body", "name"], "msg": "Field required"}, {"loc": ["body", "tasks"], "msg": "Too short"}]
    platform.say("POST", "/api/x", httpx2.Response(422, json={"detail": detail}))
    with pytest.raises(errors.Invalid) as raised:
        await d.json("POST", "/api/x", json={})
    assert raised.value.detail == "name: Field required; tasks: Too short"


async def test_a_page_that_is_not_the_api_is_not_echoed(build, platform) -> None:
    d = build("sync", retry=Retry(attempts=0))
    platform.say("GET", "/api/x", httpx2.Response(404, text="<html>internal proxy page with secrets</html>"))
    with pytest.raises(errors.NotFound) as raised:
        await d.json("GET", "/api/x")
    assert "secrets" not in str(raised.value)


async def test_a_long_sentence_is_cut(build, platform) -> None:
    d = build("sync", retry=Retry(attempts=0))
    platform.say("GET", "/api/x", httpx2.Response(409, json={"detail": "x" * 5000}))
    with pytest.raises(errors.Conflict) as raised:
        await d.json("GET", "/api/x")
    assert len(raised.value.detail) <= 300


# ---- trying again


async def test_a_read_is_tried_again_while_the_server_is_busy(build, platform, sleeps) -> None:
    for mode in ("sync", "async"):
        sleeps.clear()
        d = build(mode)
        platform.say("GET", "/api/datasets", *[httpx2.Response(503)] * 2)
        page = await d.json("GET", "/api/datasets", params={"limit": 5, "offset": 0})
        assert page["total"] == 0
        assert len(sleeps) == 2 and sleeps[1] > sleeps[0] * 1.3  # 0.5 s, then 1 s (with a little jitter)


async def test_what_the_server_asks_for_is_what_is_waited(build, platform, sleeps) -> None:
    d = build("sync")
    platform.say("GET", "/api/datasets", httpx2.Response(429, headers={"retry-after": "7"}))
    await d.json("GET", "/api/datasets", params={"limit": 5, "offset": 0})
    assert sleeps == [7.0]


async def test_a_wait_is_never_longer_than_the_limit(build, platform, sleeps) -> None:
    d = build("sync")
    platform.say("GET", "/api/datasets", httpx2.Response(429, headers={"retry-after": "100000"}))
    await d.json("GET", "/api/datasets", params={"limit": 5, "offset": 0})
    assert sleeps == [30.0]


async def test_it_gives_up_after_its_attempts_with_the_last_error(build, platform, sleeps) -> None:
    d = build("sync", retry=Retry(attempts=2))
    platform.say("GET", "/api/x", *[httpx2.Response(503, json={"detail": "busy"})] * 5)
    with pytest.raises(errors.ServerError):
        await d.json("GET", "/api/x")
    assert len(platform.api_calls("GET", "/api/x")) == 3 and len(sleeps) == 2


async def test_a_429_that_never_ends_is_a_rate_limit_error_with_its_delay(build, platform) -> None:
    d = build("sync", retry=Retry(attempts=0))
    platform.say("GET", "/api/x", httpx2.Response(429, headers={"retry-after": "12"}, json={"detail": "slow down"}))
    with pytest.raises(errors.RateLimited) as raised:
        await d.json("GET", "/api/x")
    assert raised.value.retry_after == 12.0


async def test_a_write_is_not_tried_again_unless_its_caller_says_so(build, platform) -> None:
    d = build("sync")
    platform.say("POST", "/api/x", httpx2.Response(503), httpx2.Response(200, json={"ok": 1}))
    with pytest.raises(errors.ServerError):
        await d.json("POST", "/api/x", json={})
    assert len(platform.api_calls("POST", "/api/x")) == 1  # a POST may have been done: it is not made twice

    platform.say("POST", "/api/y", httpx2.Response(503), httpx2.Response(200, json={"ok": 1}))
    assert await d.json("POST", "/api/y", json={}, retry=True) == {"ok": 1}


async def test_what_is_not_the_servers_fault_is_not_tried_again(build, platform, sleeps) -> None:
    d = build("sync")
    platform.say("GET", "/api/x", httpx2.Response(404, json={"detail": "no"}))
    with pytest.raises(errors.NotFound):
        await d.json("GET", "/api/x")
    assert sleeps == []


async def test_a_server_that_cannot_be_reached_is_one_error_that_says_nothing_of_the_address(
    platform, tmp_path, sleeps
) -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom https://api.test/secret?sig=1")

    client = Client(API, token="mh_good", transport=httpx2.MockTransport(down), sleep=sleeps.append)
    with pytest.raises(errors.ConnectionFailed) as raised:
        client.json("GET", "/api/x")
    assert "sig=1" not in str(raised.value) and raised.value.__cause__ is None
    assert len(sleeps) == 3  # it tried again before giving up

    async def adown(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom")

    async def nap(seconds: float) -> None:
        sleeps.append(seconds)

    aclient = AsyncClient(API, token="mh_good", transport=httpx2.MockTransport(adown), sleep=nap)
    with pytest.raises(errors.ConnectionFailed):
        await aclient.json("GET", "/api/x")
    await aclient.aclose()


# ---- lists


def test_a_list_is_read_page_after_page_and_stops_at_the_total(platform: FakePlatform) -> None:
    platform.datasets = [item(f"d{i:03d}") for i in range(120)]
    with Client(API, token="mh_good", transport=httpx2.MockTransport(platform)) as client:
        names = [d.name for d in client.datasets.list()]
    assert names == [f"d{i:03d}" for i in range(120)]
    pages = platform.api_calls("GET", "/api/datasets")
    assert [r.url.params["offset"] for r in pages] == ["0", "50", "100"]  # not a fourth, empty one


def test_a_list_is_read_lazily(platform: FakePlatform) -> None:
    platform.datasets = [item(f"d{i:03d}") for i in range(120)]
    with Client(API, token="mh_good", transport=httpx2.MockTransport(platform)) as client:
        first = next(iter(client.datasets.list()))
    assert first.name == "d000" and len(platform.api_calls("GET", "/api/datasets")) == 1


def test_a_filter_that_is_not_set_is_not_sent(platform: FakePlatform) -> None:
    platform.datasets = [item("sentiment"), item("other")]
    with Client(API, token="mh_good", transport=httpx2.MockTransport(platform)) as client:
        assert [d.name for d in client.datasets.list(q="sent")] == ["sentiment"]
        list(client.datasets.list())
    params = [dict(r.url.params) for r in platform.api_calls("GET", "/api/datasets")]
    assert params[0]["q"] == "sent" and "owner" not in params[0] and "q" not in params[1]


async def test_the_models_and_the_datasets_are_listed_by_both_clients(platform: FakePlatform) -> None:
    platform.datasets = [item("d1")]
    model = {**item("m1"), "tasks": ["ner"], "inputs": ["text"], "library": "", "languages": [], "parameters": None,
             "trained_on": [], "code_url": None, "version": 0, "created_by": "u", "visibility": "public"}  # fmt: skip
    model.pop("modality"), model.pop("language"), model.pop("rows")
    platform.models = [model]
    async with AsyncClient(API, token="mh_good", transport=httpx2.MockTransport(platform)) as client:
        assert [d.name async for d in client.datasets.list()] == ["d1"]
        assert [m.name async for m in client.models.list(task="ner")] == ["m1"]
    with Client(API, token="mh_good", transport=httpx2.MockTransport(platform)) as client:
        assert [m.owner for m in client.models.list()] == ["ada"]
