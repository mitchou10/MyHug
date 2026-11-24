"""The API of the platform, as the worker sees it. The worker has no database and no storage key: it asks the API what
to read, downloads from the storage with the signed address it is given, and says what it found."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx2

from worker.config import settings
from worker.errors import FileMissing


@dataclass(frozen=True)
class FileToRead:
    id: uuid.UUID
    path: str
    size_bytes: int
    url: str
    needs_fingerprint: bool
    needs_rows: bool


class Backend:
    def __init__(
        self,
        base_url: str | None = None,
        key: str | None = None,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        wait = timeout or settings.HTTP_TIMEOUT_SECONDS
        # The key goes to the API only: the storage has its own signature in the address, and must not get the key.
        self._api = httpx2.Client(
            base_url=(base_url or settings.BACKEND_URL).rstrip("/") + "/api/internal",
            headers={"X-Api-Key": key if key is not None else settings.WORKER_API_KEY},
            transport=transport,
            timeout=wait,
        )
        self._storage = httpx2.Client(transport=transport, timeout=wait)

    def _call(self, method: str, path: str, **options: Any) -> Any:
        response = self._api.request(method, path, **options)
        response.raise_for_status()
        return response.json()

    def claim(self, version_id: uuid.UUID) -> list[FileToRead] | None:
        """The files to read in the version it took in hand, or None when there is nothing for this worker to do."""
        answer = self._call("POST", f"/dataset-versions/{version_id}/claim")
        if not answer["claimed"]:
            return None
        return [
            FileToRead(
                id=uuid.UUID(file["id"]),
                path=file["path"],
                size_bytes=file["size_bytes"],
                url=file["url"],
                needs_fingerprint=file["needs_fingerprint"],
                needs_rows=file["needs_rows"],
            )
            for file in answer["files"]
        ]

    def result(self, version_id: uuid.UUID, files: list[dict[str, Any]]) -> str:
        return self._call("POST", f"/dataset-versions/{version_id}/result", json={"files": files})["status"]

    def failure(self, version_id: uuid.UUID, error: str) -> str:
        return self._call("POST", f"/dataset-versions/{version_id}/failure", json={"error": error[:2000]})["status"]

    def release(self, version_id: uuid.UUID) -> None:
        self._call("POST", f"/dataset-versions/{version_id}/release")

    def waiting(self) -> list[uuid.UUID]:
        return [uuid.UUID(item) for item in self._call("GET", "/dataset-versions/waiting")["ids"]]

    def expire_uploads(self) -> int:
        return self._call("POST", "/dataset-uploads/expire")["expired"]

    def download(self, url: str, chunk_size: int = 8 * 1024 * 1024) -> Iterator[bytes]:
        """A file as it comes, in chunks. Raises FileMissing when the storage does not have it."""
        with self._storage.stream("GET", url) as response:
            if response.status_code == 404:
                raise FileMissing("The file is missing from the storage")
            response.raise_for_status()
            yield from response.iter_bytes(chunk_size)
