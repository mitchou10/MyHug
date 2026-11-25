"""The datasets and the models of the fake platform: what `GET /api/datasets/ada/sentiment` and the like answer, with
versions that inherit the files of the one before (an upload adds, replaces, removes)."""

import hashlib
import re
from typing import Any

import httpx2

NOW = "2026-11-01T09:00:00Z"
ROUTE = re.compile(r"^/api/(datasets|models)/([^/]+)/([^/]+)(/.*)?$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_of(path: str) -> str | None:
    for word, name in (("train", "train"), ("test", "test"), ("val", "validation")):
        if word in path:
            return name
    return None


class Entity:
    def __init__(self, kind: str, owner: str, name: str) -> None:
        self.kind, self.owner, self.name = kind, owner, name
        self.versions: list[
            dict[str, Any]
        ] = []  # each: {"number", "status", "error", "message", "files": {path: bytes}, "code"}
        self.members: dict[str, str] = {}
        self.likes = 0
        self.liked = False
        self.endpoint: dict[str, Any] | None = None
        self.fields: dict[str, Any] = {}

    @property
    def address(self) -> str:
        return f"{self.owner}/{self.name}"

    def latest(self) -> dict[str, Any] | None:
        return self.versions[-1] if self.versions else None

    def file_rows(self, version: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "path": path,
                "size_bytes": len(data),
                "sha256": sha(data) if version.get("fingerprinted", True) else None,
                "content_type": "application/octet-stream",
                "split": split_of(path) if self.kind == "datasets" else None,
                "rows": None,
                "columnar": path in version.get("parquet", {}),
            }
            for path, data in sorted(version["files"].items())
        ]

    def info(self) -> dict[str, Any]:
        latest = self.latest()
        number = latest["number"] if latest else 0
        base: dict[str, Any] = {
            "id": "00000000-0000-0000-0000-000000000001", "owner": self.owner, "name": self.name, "description": "",
            "license": "", "tags": [], "visibility": "public", "downloads": 0, "likes": self.likes, "liked": self.liked,
            "version": number, "size_bytes": sum(len(d) for d in latest["files"].values()) if latest else 0,
            "created_by": "u1", "created_by_username": self.owner, "created_at": NOW, "updated_at": NOW, "card": "",
            "can_edit": True,
        }  # fmt: skip
        if self.kind == "datasets":
            splits = sorted({split_of(p) for p in (latest["files"] if latest else {}) if split_of(p)})
            base |= {
                "modality": "text", "language": "", "rows": None, "processing": None, "columns": [],
                "splits": [{"name": s, "rows": 0, "files": 1} for s in splits],
            }  # fmt: skip
        else:
            base |= {
                "tasks": ["classification"], "inputs": ["text"], "library": "", "languages": [], "code_url": None,
                "parameters": None, "trained_on": [], "serving": None,
            }  # fmt: skip
        return base | self.fields

    def version_view(self, version: dict[str, Any], *, files: bool = False) -> dict[str, Any]:
        view: dict[str, Any] = {
            "number": version["number"], "status": version["status"], "error": version.get("error"),
            "message": version.get("message", ""), "size_bytes": sum(len(d) for d in version["files"].values()),
            "created_by": "u1", "created_by_username": self.owner, "created_at": NOW,
        }  # fmt: skip
        if self.kind == "datasets":
            view |= {"rows": None, "columns": []}
        else:
            code = version.get("code")
            view |= {
                "servable": False,
                "code": {
                    "url": code["url"], "ref": code.get("ref"), "ref_kind": "unknown", "path": code.get("path"),
                    "entrypoint": code.get("entrypoint"), "sha": None, "state": "unresolved", "error": None,
                }
                if code
                else None,
            }  # fmt: skip
        if files:
            view["files"] = self.file_rows(version)
        return view


class Catalog:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.entities: dict[tuple[str, str], Entity] = {}
        self.predictions: list[Any] = []
        self.created: list[dict[str, Any]] = []
        self.parquet_asked: list[str] = []

    def add(self, kind: str, address: str, files: dict[str, bytes] | None = None, *, status: str = "ready") -> Entity:
        owner, name = address.split("/")
        entity = Entity(kind, owner, name)
        self.entities[(kind, address)] = entity
        if files is not None:
            self.new_version(entity, files, status=status)
        return entity

    def new_version(self, entity: Entity, files: dict[str, bytes], *, status: str = "ready", **extra: Any) -> dict:
        version = {"number": len(entity.versions) + 1, "status": status, "files": dict(files), **extra}
        entity.versions.append(version)
        for data in files.values():
            self.platform.files[f"blob-{sha(data)}"] = data
        return version

    # ---- routes

    def handle(self, request: httpx2.Request, body: Any) -> httpx2.Response | None:
        if request.method == "POST" and request.url.path in ("/api/datasets", "/api/models"):
            kind = request.url.path.removeprefix("/api/")
            entity = self.add(kind, f"ada/{body['name']}")
            entity.fields = {k: v for k, v in body.items() if k != "name"}
            self.created.append(body)
            return httpx2.Response(201, json=entity.info())
        found = ROUTE.match(request.url.path)
        if not found:
            return None
        kind, owner, name, rest = found.group(1), found.group(2), found.group(3), found.group(4) or ""
        method = request.method
        params = dict(request.url.params)
        if rest == "/uploads":
            return None  # the uploads are the platform's
        entity = self.entities.get((kind, f"{owner}/{name}"))
        if entity is None:
            return httpx2.Response(404, json={"detail": "This does not exist"})
        if rest == "" and method == "GET":
            return httpx2.Response(200, json=entity.info())
        if rest == "" and method == "PATCH":
            entity.fields |= body
            return httpx2.Response(200, json=entity.info())
        if rest == "" and method == "DELETE":
            del self.entities[(kind, entity.address)]
            return httpx2.Response(204)
        if rest == "/like":
            entity.liked = method == "PUT"
            entity.likes += 1 if method == "PUT" else -1
            return httpx2.Response(200, json={"liked": entity.liked, "likes": entity.likes})
        if rest == "/versions" and method == "GET":
            return httpx2.Response(200, json=[entity.version_view(v) for v in reversed(entity.versions)])
        if rest == "/versions" and method == "POST":
            version = self.new_version(
                entity,
                entity.latest()["files"] if entity.latest() else {},
                status="ready",
                code=body["code"],
                message=body.get("message", ""),
            )
            return httpx2.Response(201, json=entity.version_view(version))
        numbered = re.match(r"^/versions/(\d+)$", rest)
        if numbered:
            version = next((v for v in entity.versions if v["number"] == int(numbered.group(1))), None)
            if version is None:
                return httpx2.Response(404, json={"detail": "This version does not exist"})
            if method == "DELETE":
                entity.versions.remove(version)
                return httpx2.Response(204)
            return httpx2.Response(200, json=entity.version_view(version, files=True))
        if rest == "/files" and method == "GET":
            version = self.pick(entity, params.get("version"))
            return (
                httpx2.Response(200, json=entity.file_rows(version))
                if version
                else httpx2.Response(404, json={"detail": "No version"})
            )
        if rest.startswith("/files/") and method == "GET":
            version = self.pick(entity, params.get("version"))
            path = rest.removeprefix("/files/")
            if version is None or path not in version["files"]:
                return httpx2.Response(404, json={"detail": "This file does not exist"})
            if params.get("format") == "parquet":
                self.parquet_asked.append(path)
                data = version.get("parquet", {}).get(path)
                if data is None:
                    return httpx2.Response(404, json={"detail": "No copy of this file in Parquet is ready"})
                self.platform.files[f"blob-{sha(data)}"] = data
                return httpx2.Response(302, headers={"location": self.platform.address(f"blob-{sha(data)}")})
            return httpx2.Response(
                302, headers={"location": self.platform.address(f"blob-{sha(version['files'][path])}")}
            )
        if rest == "/members" and method == "GET":
            return httpx2.Response(
                200,
                json=[
                    {"user_id": u, "role": r, "added_by": "u1", "created_at": NOW} for u, r in entity.members.items()
                ],
            )
        member = re.match(r"^/members/([^/]+)$", rest)
        if member and method == "PUT":
            entity.members[member.group(1)] = body["role"]
            return httpx2.Response(
                200, json={"user_id": member.group(1), "role": body["role"], "added_by": "u1", "created_at": NOW}
            )
        if member and method == "DELETE":
            entity.members.pop(member.group(1), None)
            return httpx2.Response(204)
        if rest == "/endpoint":
            if method == "PUT":
                entity.endpoint = {
                    "alias": None,
                    "api": None,
                    "auth_header": None,
                    "has_auth": False,
                    "available": True,
                    "updated_at": NOW,
                    **body,
                }
            if method == "DELETE":
                entity.endpoint = None
                return httpx2.Response(204)
            if entity.endpoint is None:
                return httpx2.Response(404, json={"detail": "No endpoint"})
            return httpx2.Response(200, json=entity.endpoint)
        if rest == "/predict" and method == "POST":
            self.predictions.append(body["input"])
            return httpx2.Response(200, json={"output": {"echo": body["input"]}, "took_ms": 3})
        return None

    @staticmethod
    def pick(entity: Entity, number: str | None) -> dict[str, Any] | None:
        if number is None:
            return entity.latest()
        return next((v for v in entity.versions if v["number"] == int(number)), None)

    def announced(self, kind: str, address: str, body: dict[str, Any]) -> Entity | None:
        return self.entities.get((kind, address))

    def completed(
        self, entity: Entity, announcement: dict[str, Any], assembled: dict[str, bytes], held: dict[str, bytes]
    ) -> dict:
        """The version an upload makes: what was there, minus `remove`, plus the files sent (or already held)."""
        latest = entity.latest()
        files = dict(latest["files"]) if latest else {}
        for path in announcement["remove"]:
            files.pop(path, None)
        for item in announcement["files"]:
            data = assembled.get(item["path"], held.get(item.get("sha256") or ""))
            if data is not None:
                files[item["path"]] = data
        code = announcement.get("code")
        return self.new_version(entity, files, status="pending", message=announcement["message"], code=code)
