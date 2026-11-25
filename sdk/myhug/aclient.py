import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Self

import httpx2

from myhug import _config, _http
from myhug._retry import Retry, retry_after, retryable
from myhug.client import PAGE_SIZE
from myhug.errors import ConnectionFailed


class AsyncClient:
    """The same as `Client`, for asyncio: `async with AsyncClient(url, token) as client:`."""

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = 60.0,
        retry: Retry | None = None,
        allow_insecure: bool = False,
        cache_dir: str | Path | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.url, secret = _config.resolve(url, token, allow_insecure=allow_insecure)
        headers = {"User-Agent": _http.USER_AGENT}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        self._api = httpx2.AsyncClient(base_url=self.url, headers=headers, timeout=timeout, transport=transport)
        self._storage = httpx2.AsyncClient(
            headers={"User-Agent": _http.USER_AGENT}, timeout=timeout, transport=transport
        )
        self._retry = retry or Retry()
        self._sleep = sleep
        self.cache_dir = Path(cache_dir) if cache_dir else None
        from myhug.resources import AsyncDatasets, AsyncModels

        self.datasets = AsyncDatasets(self)
        self.models = AsyncModels(self)

    def __repr__(self) -> str:
        return f"AsyncClient({self.url!r})"

    async def _send(
        self, send: Callable[[], Awaitable[httpx2.Response]], method: str, retry: bool | None
    ) -> httpx2.Response:
        for attempt in range(self._retry.attempts + 1):
            last = attempt == self._retry.attempts
            try:
                response = await send()
            except httpx2.TransportError:
                if last or not retryable(method, None, force=retry):
                    raise ConnectionFailed("The server could not be reached") from None
                await self._sleep(self._retry.wait(attempt))
                continue
            if (
                response.status_code in (429, 502, 503, 504)
                and not last
                and retryable(method, response.status_code, force=retry)
            ):
                await self._sleep(self._retry.wait(attempt, retry_after(response.headers.get("retry-after"))))
                continue
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        retry: bool | None = None,
    ) -> httpx2.Response:
        response = await self._send(
            lambda: self._api.request(method, path, params=_http.clean(params), json=json), method, retry
        )
        if response.is_error:
            raise _http.error_of(response)
        return response

    async def json(self, method: str, path: str, **options: Any) -> Any:
        return _http.result_of(await self.request(method, path, **options))

    async def paginate(self, path: str, params: dict[str, Any] | None = None) -> AsyncIterator[dict[str, Any]]:
        offset = 0
        while True:
            page = await self.json("GET", path, params={**(params or {}), "limit": PAGE_SIZE, "offset": offset})
            for item in page["items"]:
                yield item
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"]:
                return

    async def storage(
        self, method: str, url: str, *, headers: dict[str, str] | None = None, content: bytes | None = None
    ) -> httpx2.Response:
        return await self._send(
            lambda: self._storage.request(method, url, headers=headers, content=content), method, None
        )

    def stream_storage(self, url: str, *, headers: dict[str, str] | None = None):
        return self._storage.stream("GET", url, headers=headers)

    async def aclose(self) -> None:
        await self._api.aclose()
        await self._storage.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
