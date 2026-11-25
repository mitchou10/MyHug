"""The platform in memory, behind an `httpx2.MockTransport`: the API (with the rules the SDK relies on: redirection to a
signed address, uploads in parts that can be asked about) and a storage (which does ranges, and can be made to fail)."""

import hashlib
import json
import re
import threading
import uuid
from collections.abc import Callable
from typing import Any

import httpx2

from tests.catalog import Catalog

API = "https://api.test"
STORAGE = "storage.test"


class Broken(httpx2.SyncByteStream, httpx2.AsyncByteStream):
    """A body that gives some bytes and then the connection drops."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def __iter__(self):
        yield self.data
        raise httpx2.ReadError("connection lost")

    async def __aiter__(self):
        yield self.data
        raise httpx2.ReadError("connection lost")


class FakePlatform:
    def __init__(self, token: str = "mh_good") -> None:
        self.token = token
        self.lock = threading.Lock()
        self.requests: list[httpx2.Request] = []
        # The API
        self.datasets: list[dict] = []
        self.models: list[dict] = []
        self.files: dict[str, bytes] = {}  # path of a file served for download -> its content
        self.answers: dict[tuple[str, str], list[httpx2.Response]] = {}  # (method, path) -> answers to give first
        # Uploads
        self.uploads: dict[str, dict] = {}
        self.parts: dict[tuple[str, str, int], bytes] = {}
        self.held: set[str] = set()  # sha256 of the files the platform already holds
        self.assembled: dict[str, bytes] = {}
        self.completed: list[dict] = []
        self.announced: list[dict] = []
        # The storage
        self.refuse_parts = 0  # the next PUTs of a part are refused
        self.refuse_gets = 0  # the next downloads are refused with 403 (an address that expired)
        self.honour_range = True
        self.break_after: int | None = None  # the next download drops after this many bytes
        self.storage_calls: list[tuple[str, str, dict]] = []  # (method, path, headers)
        self.signed = 0
        self.running = 0
        self.most_running = 0
        self.catalog = Catalog(self)
        self.upload_entity: dict[
            str, tuple[Any, dict]
        ] = {}  # upload id -> the dataset or model it is for, its announcement

    # ---- helpers for the tests

    def say(self, method: str, path: str, *responses: httpx2.Response) -> None:
        """The next calls to this route get these answers (then the normal one)."""
        self.answers[(method, path)] = list(responses)

    def api_calls(self, method: str | None = None, path: str | None = None) -> list[httpx2.Request]:
        return [
            r
            for r in self.requests
            if r.url.host == "api.test"
            and (method is None or r.method == method)
            and (path is None or r.url.path == path)
        ]

    # ---- the transport

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        with self.lock:
            self.requests.append(request)
        if request.url.host == STORAGE:
            return self.storage(request)
        return self.api(request)

    def api(self, request: httpx2.Request) -> httpx2.Response:
        method, path = request.method, request.url.path
        with self.lock:
            queued = self.answers.get((method, path))
            if queued:
                return queued.pop(0)
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx2.Response(401, json={"detail": "Not authenticated"})
        params = dict(request.url.params)
        body: Any = json.loads(request.content) if request.content else None

        if method == "GET" and path in ("/api/datasets", "/api/models"):
            items = self.datasets if path == "/api/datasets" else self.models
            q = params.get("q")
            found = [i for i in items if not q or q in i["name"]]
            limit, offset = int(params["limit"]), int(params["offset"])
            return httpx2.Response(
                200,
                json={"items": found[offset : offset + limit], "total": len(found), "limit": limit, "offset": offset},
            )
        if method == "GET" and path.startswith("/api/files/"):
            name = path.removeprefix("/api/files/")
            if name not in self.files:
                return httpx2.Response(404, json={"detail": "This file does not exist"})
            return httpx2.Response(302, headers={"location": self.address(name)})
        if method == "GET" and path == "/api/nowhere":
            return httpx2.Response(200, json={"not": "a redirection"})
        answer = self.catalog.handle(request, body)
        if answer is not None:
            return answer
        return self.uploads_api(request, method, path, body, params)

    def address(self, name: str) -> str:
        with self.lock:
            self.signed += 1
            return f"https://{STORAGE}/get/{name}?sig={self.signed}"

    def uploads_api(self, request: httpx2.Request, method: str, path: str, body: Any, params: dict) -> httpx2.Response:
        upload_route = re.match(r"^/api/(datasets|models)/([^/]+)/([^/]+)/uploads$", path)
        if method == "POST" and upload_route:
            kind, address = upload_route.group(1), f"{upload_route.group(2)}/{upload_route.group(3)}"
            if kind == "datasets" and address == "ada/sentiment" and (kind, address) not in self.catalog.entities:
                return self.announce(body, "/api/uploads")  # the engine tests need no dataset behind
            if kind == "models" and address == "ada/sentiment" and (kind, address) not in self.catalog.entities:
                return self.announce(body, "/api/model-uploads")
            entity = self.catalog.entities.get((kind, address))
            if entity is None:
                return httpx2.Response(404, json={"detail": "This does not exist"})
            response = self.announce(body, "/api/uploads" if kind == "datasets" else "/api/model-uploads")
            self.upload_entity[response.json()["id"]] = (entity, body)
            return response
        for prefix in ("/api/uploads", "/api/model-uploads"):
            if not path.startswith(prefix + "/"):
                continue
            upload_id, _, action = path.removeprefix(prefix + "/").partition("/")
            upload = self.uploads.get(upload_id)
            if upload is None or upload["status"] == "aborted":
                return httpx2.Response(404, json={"detail": "This upload does not exist"})
            if method == "GET":
                return httpx2.Response(200, json=self.view(upload, parts=params.get("parts") == "true"))
            if method == "DELETE":
                upload["status"] = "aborted"
                return httpx2.Response(204)
            if action == "parts":
                numbers = body["numbers"]
                return httpx2.Response(
                    200,
                    json={
                        "parts": [
                            {
                                "number": n,
                                "url": f"https://{STORAGE}/put/{upload_id}/{body['file_id']}/{n}?sig={self.next_sig()}",
                            }
                            for n in numbers
                        ],
                        "expires_in": 600,
                    },
                )
            if action == "complete":
                for entry in upload["files"]:
                    if entry["already_stored"]:
                        continue
                    if any((upload_id, entry["id"], n) not in self.parts for n in range(1, entry["parts_count"] + 1)):
                        return httpx2.Response(409, json={"detail": "Some parts are missing"})
                    self.assembled[entry["path"]] = b"".join(
                        self.parts[(upload_id, entry["id"], n)] for n in range(1, entry["parts_count"] + 1)
                    )
                    upload.setdefault("assembled", {})[entry["path"]] = self.assembled[entry["path"]]
                upload["status"] = "completed"
                self.completed.append(upload)
                entity, announcement = self.upload_entity.get(upload_id, (None, {}))
                if entity is not None:
                    held = {k.removeprefix("blob-"): v for k, v in self.files.items() if k.startswith("blob-")}
                    version = self.catalog.completed(entity, announcement, upload.pop("assembled", {}), held)
                    return httpx2.Response(200, json=entity.version_view(version))
                return httpx2.Response(200, json={"number": len(self.completed), "status": "pending"})
        return httpx2.Response(404, json={"detail": "No such route"})

    def next_sig(self) -> int:
        with self.lock:
            self.signed += 1
            return self.signed

    def announce(self, body: dict, prefix: str) -> httpx2.Response:
        upload_id = uuid.uuid4().hex
        self.announced.append(body)
        part_bytes = 4
        files = []
        for i, f in enumerate(body["files"]):
            files.append(
                {
                    "id": f"{upload_id}-{i}",
                    "path": f["path"],
                    "size_bytes": f["size"],
                    "part_size": part_bytes,
                    "parts_count": -(-f["size"] // part_bytes),
                    "already_stored": bool(f.get("sha256")) and f["sha256"] in self.held,
                }
            )
        self.uploads[upload_id] = {
            "id": upload_id,
            "status": "open",
            "expires_at": "2030-01-01T00:00:00Z",
            "version": None,
            "files": files,
        }
        return httpx2.Response(201, json=self.view(self.uploads[upload_id], parts=False))

    def view(self, upload: dict, *, parts: bool) -> dict:
        files = []
        for entry in upload["files"]:
            received = None
            if parts:
                received = [
                    {"number": n, "size": len(data)}
                    for (uid, fid, n), data in sorted(self.parts.items())
                    if uid == upload["id"] and fid == entry["id"]
                ]
            files.append({**entry, "received": received})
        return {**upload, "files": files}

    def storage(self, request: httpx2.Request) -> httpx2.Response:
        method, path = request.method, request.url.path
        with self.lock:
            self.storage_calls.append((method, path, dict(request.headers)))
        if method == "PUT":
            with self.lock:
                self.running += 1
                self.most_running = max(self.most_running, self.running)
            try:
                with self.lock:
                    if self.refuse_parts > 0:
                        self.refuse_parts -= 1
                        return httpx2.Response(403)
                _, upload_id, file_id, number = path.strip("/").split("/")
                with self.lock:
                    self.parts[(upload_id, file_id, int(number))] = request.content
                return httpx2.Response(200)
            finally:
                with self.lock:
                    self.running -= 1
        with self.lock:
            if self.refuse_gets > 0:
                self.refuse_gets -= 1
                return httpx2.Response(403)
        data = self.files[path.removeprefix("/get/")]
        asked = request.headers.get("range")
        start = 0
        stop = len(data)
        status = 200
        extra: dict[str, str] = {}
        if asked and self.honour_range:
            first, _, last = asked.removeprefix("bytes=").partition("-")
            start = int(first)
            stop = min(len(data), int(last) + 1) if last else len(data)
            if start >= len(data):
                return httpx2.Response(416)
            status = 206
            extra = {"content-range": f"bytes {start}-{stop - 1}/{len(data)}"}
        body = data[start:stop]
        headers = {"content-length": str(len(body)), **extra}
        if self.break_after is not None:
            cut, self.break_after = self.break_after, None
            return httpx2.Response(status, headers=headers, stream=Broken(body[:cut]))
        return httpx2.Response(status, headers=headers, content=body)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


Handler = Callable[[httpx2.Request], httpx2.Response]
