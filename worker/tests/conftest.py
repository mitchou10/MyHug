import hashlib
import uuid
from collections.abc import Callable

import httpx2
import pytest

from worker import tasks
from worker.backend import Backend

KEY = "worker-key-of-sixteen-characters"
CSV = b"n\n1\n2\n3\n"


class FakePlatform:
    """The API and the storage, as the worker meets them: an httpx transport that answers like them, and remembers what
    the worker said."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}  # signed address -> content
        self.to_read: list[dict] | None = []  # what `claim` answers (None: nothing to do)
        self.calls: list[tuple[str, str]] = []
        self.bodies: dict[str, dict] = {}
        self.keys: list[str | None] = []
        self.storage_failure: int | None = None  # a status the storage answers instead
        self.waiting_ids: list[str] = []
        self.waiting_model_ids: list[str] = []
        self.waiting_code_ids: list[str] = []
        self.code: dict | None = None  # what `claim` of the code answers (None: nothing to do)
        self.waiting_copy_ids: list[str] = []
        self.copy: dict | None = None  # what `claim` of a copy answers (None: nothing to do)
        self.uploaded: dict[int, bytes] = {}  # the parts of the copy that reached the storage
        self.collections: list[dict] = []  # what each pass of the collection answers, in turn

    def add_file(self, path: str, data: bytes, *, rows: bool = True, fingerprint: bool = True) -> dict:
        url = f"https://storage.test/{uuid.uuid4().hex}/{path}"
        self.files[url] = data
        return {
            "id": str(uuid.uuid4()),
            "path": path,
            "size_bytes": len(data),
            "url": url,
            "needs_fingerprint": fingerprint,
            "needs_rows": rows,
        }

    def handle_copy(self, path: str) -> httpx2.Response:
        if path.endswith("/claim"):
            if self.copy is None:
                return httpx2.Response(200, json={"claimed": False})
            return httpx2.Response(200, json={"claimed": True, **self.copy})
        if path.endswith("/parts"):
            numbers = self.bodies[path]["numbers"]
            return httpx2.Response(
                200, json={"parts": [{"number": n, "url": f"https://storage.test/up/{n}"} for n in numbers]}
            )
        if path.endswith("/result"):
            return httpx2.Response(200, json={"status": "ready"})
        if path.endswith("/failure"):
            return httpx2.Response(200, json={"status": "failed"})
        if path.endswith("/release"):
            return httpx2.Response(200, json={"status": "pending"})
        if path.endswith("/waiting"):
            return httpx2.Response(200, json={"ids": self.waiting_copy_ids})
        return httpx2.Response(404)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "storage.test":
            self.keys.append(request.headers.get("X-Api-Key"))
            if request.method == "PUT":
                if self.storage_failure:
                    return httpx2.Response(self.storage_failure)
                self.uploaded[int(request.url.path.rsplit("/", 1)[1])] = request.content
                return httpx2.Response(200)
            if self.storage_failure:
                return httpx2.Response(self.storage_failure)
            data = self.files.get(str(request.url))
            return httpx2.Response(200, content=data) if data is not None else httpx2.Response(404)
        self.keys.append(request.headers.get("X-Api-Key"))
        path = request.url.path.removeprefix("/api/internal")
        self.calls.append((request.method, path))
        if request.content:
            import json

            self.bodies[path] = json.loads(request.content)
        if path == "/storage/collect":
            return httpx2.Response(200, json=self.collections.pop(0))
        if "/code/" in path:
            if path.endswith("/claim"):
                if self.code is None:
                    return httpx2.Response(200, json={"claimed": False})
                return httpx2.Response(200, json={"claimed": True, **self.code})
            states = {"pinned": "pinned", "unverified": "unverified", "failure": "failed", "release": "unresolved"}
            return httpx2.Response(200, json={"state": states[path.rsplit("/", 1)[1]]})
        if path.startswith("/derivatives/"):
            return self.handle_copy(path)
        if path.endswith("/claim"):
            if self.to_read is None:
                return httpx2.Response(200, json={"claimed": False, "files": []})
            return httpx2.Response(200, json={"claimed": True, "files": self.to_read})
        if path.endswith("/result"):
            return httpx2.Response(200, json={"status": "ready"})
        if path.endswith("/failure"):
            return httpx2.Response(200, json={"status": "failed"})
        if path.endswith("/release"):
            return httpx2.Response(200, json={"status": "pending"})
        if path == "/model-code/waiting":
            return httpx2.Response(200, json={"ids": self.waiting_code_ids})
        if path == "/model-versions/waiting":
            return httpx2.Response(200, json={"ids": self.waiting_model_ids})
        if path.endswith("/waiting"):
            return httpx2.Response(200, json={"ids": self.waiting_ids})
        if path.endswith("/expire"):
            return httpx2.Response(200, json={"expired": 2})
        return httpx2.Response(404)


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> FakePlatform:
    fake = FakePlatform()
    monkeypatch.setattr(
        tasks, "_backend", lambda: Backend("http://api.test", KEY, transport=httpx2.MockTransport(fake.handle))
    )
    return fake


@pytest.fixture
def backend() -> Callable[[FakePlatform], Backend]:
    return lambda fake: Backend("http://api.test", KEY, transport=httpx2.MockTransport(fake.handle))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
