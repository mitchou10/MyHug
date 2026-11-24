import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx2

from app.services.errors import (
    BadEndpointAnswer,
    EndpointTimeout,
    EndpointUnavailable,
    InputRejected,
)
from app.serving.addresses import check_endpoint_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Prediction:
    body: Any
    took_ms: int


class ServingClient:
    """Calls the server that serves a model. It is the only place the backend calls an address that people wrote.

    Every address is checked against the allowlist **at the moment of the call**, no redirect is followed (it is an
    error), nothing is sent but the JSON that was asked for, the answer is read up to a limit, and what the server says
    about itself (its errors, its headers) is never passed on: a reader gets the same few sentences whatever happened
    inside."""

    def __init__(
        self,
        *,
        origins: list[str],
        timeout: float,
        max_response_bytes: int,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._origins = origins
        self._timeout = timeout
        self._max_bytes = max_response_bytes
        self._transport = transport

    def _client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(timeout=self._timeout, follow_redirects=False, transport=self._transport)

    async def ping(self, url: str, header: tuple[str, str] | None = None) -> bool:
        """Whether an MLflow model server answers at this address (`GET {url}/ping`)."""
        address = check_endpoint_url(url, self._origins)
        try:
            async with self._client() as client:
                response = await client.get(f"{address}/ping", headers=dict([header]) if header else None)
        except httpx2.HTTPError:
            return False
        return response.status_code == 200

    async def call(self, url: str, body: Any, header: tuple[str, str] | None = None) -> Prediction:
        """POSTs `body` as JSON and returns the JSON that comes back. Raises EndpointTimeout, EndpointUnavailable
        (down, redirects, refuses the platform), InputRejected (it refuses this input) and BadEndpointAnswer."""
        address = check_endpoint_url(url, self._origins)
        headers = {"Accept": "application/json", **dict([header] if header else [])}
        started = time.monotonic()
        try:
            async with (
                self._client() as client,
                client.stream("POST", address, json=body, headers=headers) as response,
            ):
                status = response.status_code
                if status in (400, 415, 422, 413):
                    raise InputRejected
                if status >= 300:
                    # 3xx (never followed), 401/403 (the platform's login is wrong), 404, 429, 5xx: the model cannot be
                    # tried now, and what the server says is not for the person who tried.
                    logger.warning("The endpoint %s answered %s", address, status)
                    raise EndpointUnavailable
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > self._max_bytes:
                        raise BadEndpointAnswer("The answer of the model is too large")
        except httpx2.TimeoutException:
            raise EndpointTimeout from None
        except httpx2.HTTPError:
            raise EndpointUnavailable from None
        try:
            parsed = json.loads(bytes(data))
        except ValueError:
            raise BadEndpointAnswer from None
        return Prediction(parsed, int((time.monotonic() - started) * 1000))
