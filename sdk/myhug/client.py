import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Self

import httpx2

from myhug import _config, _http
from myhug._retry import Retry, retry_after, retryable
from myhug.errors import ConnectionFailed

PAGE_SIZE = 50


class Client:
    """The platform, for a program: `Client("https://myhug.example", token="mh_...")`, or `MYHUG_URL` and `MYHUG_TOKEN`.

    Two HTTP clients: one for the API (it carries the token and never follows a redirect by itself), one for the storage
    (the signed addresses the API gives): the token never goes there."""

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = 60.0,
        retry: Retry | None = None,
        allow_insecure: bool = False,
        cache_dir: str | Path | None = None,
        transport: httpx2.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.url, secret = _config.resolve(url, token, allow_insecure=allow_insecure)
        headers = {"User-Agent": _http.USER_AGENT}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        self._api = httpx2.Client(base_url=self.url, headers=headers, timeout=timeout, transport=transport)
        self._storage = httpx2.Client(headers={"User-Agent": _http.USER_AGENT}, timeout=timeout, transport=transport)
        self._retry = retry or Retry()
        self._sleep = sleep
        self.cache_dir = Path(cache_dir) if cache_dir else None
        from myhug.resources import Datasets, Models

        self.datasets = Datasets(self)
        self.models = Models(self)

    def __repr__(self) -> str:  # no token in it
        return f"Client({self.url!r})"

    # ---- calls

    def _send(self, send: Callable[[], httpx2.Response], method: str, retry: bool | None) -> httpx2.Response:
        """Makes a call, and makes it again as many times as the policy says when the server is busy or not there."""
        for attempt in range(self._retry.attempts + 1):
            last = attempt == self._retry.attempts
            try:
                response = send()
            except httpx2.TransportError:
                if last or not retryable(method, None, force=retry):
                    raise ConnectionFailed("The server could not be reached") from None
                self._sleep(self._retry.wait(attempt))
                continue
            if (
                response.status_code in (429, 502, 503, 504)
                and not last
                and retryable(method, response.status_code, force=retry)
            ):
                self._sleep(self._retry.wait(attempt, retry_after(response.headers.get("retry-after"))))
                continue
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        retry: bool | None = None,
    ) -> httpx2.Response:
        """A call to the API. It raises the exception of an error status; a redirection is given back, not followed."""
        response = self._send(
            lambda: self._api.request(method, path, params=_http.clean(params), json=json), method, retry
        )
        if response.is_error:
            raise _http.error_of(response)
        return response

    def json(self, method: str, path: str, **options: Any) -> Any:
        return _http.result_of(self.request(method, path, **options))

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """The items of a list that comes in pages (`items`, `total`, `limit`, `offset`), page after page."""
        offset = 0
        while True:
            page = self.json("GET", path, params={**(params or {}), "limit": PAGE_SIZE, "offset": offset})
            yield from page["items"]
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"]:
                return

    def storage(
        self, method: str, url: str, *, headers: dict[str, str] | None = None, content: bytes | None = None
    ) -> httpx2.Response:
        """A call to a signed address of the storage. Never given the token; an error here never repeats the address."""
        response = self._send(
            lambda: self._storage.request(method, url, headers=headers, content=content), method, None
        )
        return response

    def stream_storage(self, url: str, *, headers: dict[str, str] | None = None):
        """A streamed GET of a signed address (the body is read by the caller)."""
        return self._storage.stream("GET", url, headers=headers)

    # ---- life

    def close(self) -> None:
        self._api.close()
        self._storage.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
