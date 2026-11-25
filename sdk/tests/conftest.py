import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from myhug import AsyncClient, Client
from tests.fake import API, FakePlatform


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform()


@pytest.fixture
def sleeps() -> list[float]:
    """Nothing really waits in the tests: what was asked to wait is here."""
    return []


class Driver:
    """The two clients behind the same calls: a test is written once and run for the blocking and the asyncio one."""

    def __init__(self, mode: str, platform: FakePlatform, cache: Path, sleeps: list[float], **options: Any) -> None:
        self.mode = mode
        self.platform = platform
        common = {"cache_dir": cache, "token": "mh_good", **options}
        if mode == "sync":
            self.client = Client(API, transport=httpx2.MockTransport(platform), sleep=sleeps.append, **common)
        else:

            async def nap(seconds: float) -> None:
                sleeps.append(seconds)

            self.client = AsyncClient(API, transport=httpx2.MockTransport(platform), sleep=nap, **common)

    async def call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """`function(client, ...)` for the blocking client (in a thread), awaited for the async one."""
        if self.mode == "sync":
            return await asyncio.to_thread(function, self.client, *args, **kwargs)
        return await function(self.client, *args, **kwargs)

    async def json(self, method: str, path: str, **options: Any) -> Any:
        if self.mode == "sync":
            return await asyncio.to_thread(self.client.json, method, path, **options)
        return await self.client.json(method, path, **options)


@pytest.fixture(params=["sync", "async"])
async def driver(
    request: pytest.FixtureRequest, platform: FakePlatform, tmp_path: Path, sleeps: list[float]
) -> AsyncIterator[Driver]:
    d = Driver(request.param, platform, tmp_path / "cache", sleeps)
    yield d
    if d.mode == "sync":
        d.client.close()
    else:
        await d.client.aclose()


@pytest.fixture
async def build(platform: FakePlatform, tmp_path: Path, sleeps: list[float]) -> AsyncIterator[Callable[..., Driver]]:
    """A driver with options (`build("sync", retry=Retry(attempts=1))`), for the tests of the client itself."""
    made: list[Driver] = []

    def _build(mode: str, **options: Any) -> Driver:
        made.append(Driver(mode, platform, tmp_path / "cache", sleeps, **options))
        return made[-1]

    yield _build
    for d in made:
        if d.mode == "sync":
            d.client.close()
        else:
            await d.client.aclose()
