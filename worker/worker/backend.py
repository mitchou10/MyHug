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


@dataclass(frozen=True)
class CodeToResolve:
    url: str
    ref: str | None
    ref_kind: str


@dataclass(frozen=True)
class CopyToMake:
    id: uuid.UUID
    source_url: str
    source_path: str
    source_size_bytes: int
    part_bytes: int


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

    # ---- the files of the versions of the models

    def claim_model_version(self, version_id: uuid.UUID) -> list[FileToRead] | None:
        """The files to fingerprint in the version it took in hand, or None when there is nothing for this worker."""
        answer = self._call("POST", f"/model-versions/{version_id}/claim")
        if not answer["claimed"]:
            return None
        return [
            FileToRead(
                id=uuid.UUID(file["id"]),
                path=file["path"],
                size_bytes=file["size_bytes"],
                url=file["url"],
                needs_fingerprint=True,
                needs_rows=False,
            )
            for file in answer["files"]
        ]

    def model_version_result(self, version_id: uuid.UUID, files: list[dict[str, Any]]) -> str:
        return self._call("POST", f"/model-versions/{version_id}/result", json={"files": files})["status"]

    def model_version_failure(self, version_id: uuid.UUID, error: str) -> str:
        return self._call("POST", f"/model-versions/{version_id}/failure", json={"error": error[:2000]})["status"]

    def model_version_release(self, version_id: uuid.UUID) -> None:
        self._call("POST", f"/model-versions/{version_id}/release")

    def waiting_model_versions(self) -> list[uuid.UUID]:
        return [uuid.UUID(item) for item in self._call("GET", "/model-versions/waiting")["ids"]]

    # ---- the code of the versions of the models

    def claim_code(self, version_id: uuid.UUID) -> "CodeToResolve | None":
        answer = self._call("POST", f"/model-versions/{version_id}/code/claim")
        if not answer["claimed"]:
            return None
        return CodeToResolve(url=answer["url"], ref=answer["ref"], ref_kind=answer["ref_kind"])

    def code_pinned(self, version_id: uuid.UUID, sha: str) -> str:
        return self._call("POST", f"/model-versions/{version_id}/code/pinned", json={"sha": sha})["state"]

    def code_unverified(self, version_id: uuid.UUID, reason: str) -> str:
        return self._call("POST", f"/model-versions/{version_id}/code/unverified", json={"reason": reason[:2000]})[
            "state"
        ]

    def code_failure(self, version_id: uuid.UUID, reason: str) -> str:
        return self._call("POST", f"/model-versions/{version_id}/code/failure", json={"reason": reason[:2000]})["state"]

    def code_release(self, version_id: uuid.UUID) -> None:
        self._call("POST", f"/model-versions/{version_id}/code/release")

    def waiting_code(self) -> list[uuid.UUID]:
        return [uuid.UUID(item) for item in self._call("GET", "/model-code/waiting")["ids"]]

    # ---- the Parquet copies

    def claim_copy(self, derivative_id: uuid.UUID) -> "CopyToMake | None":
        answer = self._call("POST", f"/derivatives/{derivative_id}/claim")
        if not answer["claimed"]:
            return None
        return CopyToMake(
            id=uuid.UUID(answer["id"]),
            source_url=answer["source_url"],
            source_path=answer["source_path"],
            source_size_bytes=answer["source_size_bytes"],
            part_bytes=answer["part_bytes"],
        )

    def sign_copy_parts(self, derivative_id: uuid.UUID, numbers: list[int]) -> dict[int, str]:
        answer = self._call("POST", f"/derivatives/{derivative_id}/parts", json={"numbers": numbers})
        return {part["number"]: part["url"] for part in answer["parts"]}

    def copy_result(self, derivative_id: uuid.UUID, rows: int, columns: list[dict[str, str]]) -> str:
        return self._call("POST", f"/derivatives/{derivative_id}/result", json={"rows": rows, "columns": columns})[
            "status"
        ]

    def copy_failure(self, derivative_id: uuid.UUID, error: str) -> str:
        return self._call("POST", f"/derivatives/{derivative_id}/failure", json={"error": error[:2000]})["status"]

    def copy_release(self, derivative_id: uuid.UUID) -> None:
        self._call("POST", f"/derivatives/{derivative_id}/release")

    def waiting_copies(self) -> list[uuid.UUID]:
        return [uuid.UUID(item) for item in self._call("GET", "/derivatives/waiting")["ids"]]

    def upload_part(self, url: str, data: bytes) -> None:
        """Sends one part of a copy to its signed address. A refusal or a down storage is an error of the job."""
        self._storage.put(url, content=data).raise_for_status()

    def collect_storage(self, after: str | None = None) -> dict[str, Any]:
        """One pass of the collection of the objects nothing points to: the backend looks, decides and deletes."""
        return self._call("POST", "/storage/collect", json={"after": after})

    def download(self, url: str, chunk_size: int = 8 * 1024 * 1024) -> Iterator[bytes]:
        """A file as it comes, in chunks. Raises FileMissing when the storage does not have it."""
        with self._storage.stream("GET", url) as response:
            if response.status_code == 404:
                raise FileMissing("The file is missing from the storage")
            response.raise_for_status()
            yield from response.iter_bytes(chunk_size)
