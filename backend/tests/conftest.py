import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

# The database the tests run against (docker compose -f docker-compose.test.yaml up -d --wait). Set before the app
# is imported: its settings are read once.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:app@localhost:55433/app")

from collections.abc import AsyncIterator, Callable, Iterator  # noqa: E402

import httpx2  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.auth.context import RequestContext  # noqa: E402
from app.auth.deps import get_current_user  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.jobs import NoJobs  # noqa: E402
from app.main import app  # noqa: E402
from app.registry import RegistryArtifact, RegistryRun, RegistryVersion, get_registry  # noqa: E402
from app.routers.deps import get_jobs  # noqa: E402
from app.services.errors import RegistryConflict, RegistryNotFound, RegistryRejected, RegistryUnavailable  # noqa: E402
from app.storage import (  # noqa: E402
    ListedObject,
    ObjectInfo,
    ObjectListing,
    ObjectNotFound,
    PartInfo,
    StartedUpload,
    StoredObject,
    get_store,
)

SEEDED = ("feedback_types", "feedback_statuses")
RESET = (
    "TRUNCATE feedback_attachments, feedback_messages, feedbacks, feedback_types, feedback_statuses, "
    "user_profiles, notifications, dataset_likes, dataset_members, dataset_upload_files, dataset_uploads, "
    "dataset_file_derivatives, dataset_files, dataset_versions, datasets, "
    "model_endpoints, model_upload_files, model_uploads, model_files, model_versions, model_members, model_likes, "
    "model_evaluations, models, access_tokens, annotations, annotation_labels, annotation_tasks"
)


async def _sql(*statements: str) -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))
    await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[None]:
    """The schema comes from the migrations, so they are tested too: from scratch, with the default types and statuses.

    A copy of those defaults is kept (`_seed_*`), so each test can start from them without repeating them here."""
    config = Config("alembic.ini")
    asyncio.run(_sql(*(f"DROP TABLE IF EXISTS _seed_{table}" for table in SEEDED)))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    asyncio.run(_sql(*(f"CREATE TABLE _seed_{table} AS TABLE {table}" for table in SEEDED)))
    yield
    # `alembic check` must not find tables the models do not know.
    asyncio.run(_sql(*(f"DROP TABLE IF EXISTS _seed_{table}" for table in SEEDED)))


@pytest.fixture
async def db(migrated_database: None) -> AsyncIterator[AsyncSession]:
    # NullPool: a connection belongs to the event loop of the test that opened it.
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text(RESET))
        for table in SEEDED:
            await connection.execute(text(f"INSERT INTO {table} SELECT * FROM _seed_{table}"))
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        app.dependency_overrides[get_db] = lambda: session
        yield session
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


class MemoryStore:
    """In place of RustFS."""

    @staticmethod
    def stored(data: bytes, content_type: str = "text/csv") -> StoredObject:
        return StoredObject(data=data, content_type=content_type)

    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        # Files being uploaded in parts: upload id -> where it goes, and the parts that arrived.
        self.uploads: dict[str, dict] = {}
        # Since when each object is there (a listing gives it): tests set it to make an object old.
        self.modified: dict[str, datetime] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = StoredObject(data=data, content_type=content_type)
        self.modified[key] = datetime.now(UTC)

    def age(self, key: str, by: timedelta) -> None:
        """Makes an object, or a started upload, `by` older than it is."""
        if key in self.objects:
            self.modified[key] = datetime.now(UTC) - by
        for upload in self.uploads.values():
            if upload["key"] == key:
                upload["initiated"] = datetime.now(UTC) - by

    async def get(self, key: str) -> StoredObject | None:
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.modified.pop(key, None)

    async def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            await self.delete(key)

    async def list_objects(self, prefix: str, *, after: str | None = None, limit: int = 1000) -> ObjectListing:
        keys = sorted(k for k in self.objects if k.startswith(prefix) and (after is None or k > after))
        page = keys[: min(limit, 1000)]
        items = [
            ListedObject(key=k, size=len(self.objects[k].data), modified=self.modified.get(k, datetime.now(UTC)))
            for k in page
        ]
        return ObjectListing(items=items, next_after=page[-1] if len(keys) > len(page) else None)

    async def list_started_uploads(self, prefix: str) -> list[StartedUpload]:
        return [
            StartedUpload(key=u["key"], upload_id=upload_id, initiated=u["initiated"])
            for upload_id, u in self.uploads.items()
            if u["key"].startswith(prefix)
        ]

    async def stream(self, key: str, chunk_size: int = 8 * 1024 * 1024) -> AsyncIterator[bytes]:
        stored = self.objects.get(key)
        if stored is None:
            raise ObjectNotFound(key)
        for start in range(0, len(stored.data), chunk_size):
            yield stored.data[start : start + chunk_size]

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        stored = self.objects.get(key)
        if stored is None:
            raise ObjectNotFound(key)
        return stored.data[start : start + length]

    async def head(self, key: str) -> ObjectInfo | None:
        stored = self.objects.get(key)
        return ObjectInfo(size=len(stored.data), content_type=stored.content_type) if stored else None

    async def create_multipart(self, key: str, content_type: str) -> str:
        upload_id = uuid.uuid4().hex
        self.uploads[upload_id] = {
            "key": key,
            "content_type": content_type,
            "parts": {},
            "initiated": datetime.now(UTC),
        }
        return upload_id

    async def presign_part(
        self, key: str, upload_id: str, number: int, expires_in: int, *, internal: bool = False
    ) -> str:
        return f"memory://{upload_id}/{number}"

    def receive(self, url: str, data: bytes) -> str:
        """What the browser does with a signed address: it sends the part there. Returns the fingerprint of the part."""
        upload_id, number = url.removeprefix("memory://").split("/")
        etag = hashlib.md5(data).hexdigest()  # noqa: S324
        self.uploads[upload_id]["parts"][int(number)] = (data, etag)
        return etag

    async def list_parts(self, key: str, upload_id: str) -> list[PartInfo]:
        parts = self.uploads[upload_id]["parts"]
        return [PartInfo(number=n, size=len(data), etag=etag) for n, (data, etag) in sorted(parts.items())]

    async def complete_multipart(self, key: str, upload_id: str, parts: list[PartInfo]) -> None:
        upload = self.uploads.pop(upload_id)
        data = b"".join(upload["parts"][part.number][0] for part in sorted(parts, key=lambda p: p.number))
        self.objects[key] = StoredObject(data=data, content_type=upload["content_type"])
        self.modified[key] = datetime.now(UTC)

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        self.uploads.pop(upload_id, None)

    async def presign_get(
        self, key: str, expires_in: int, filename: str | None = None, *, internal: bool = False
    ) -> str:
        return f"memory://get/{key}"


class MemoryRegistry:
    """In place of MLflow. It keeps what is made, remembers the calls in order (`calls`), and refuses what MLflow
    refuses: a name with `/` or `:`, a name taken, a model or a version that is not there.

    `down = True`: MLflow does not answer. `fail_on = "create_version"`: that one call fails (the rest works)."""

    def __init__(self, prefix: str = "mlflow/") -> None:
        self.models: set[str] = set()
        self.runs: dict[str, dict] = {}
        self.versions: dict[tuple[str, str], RegistryVersion] = {}
        self.aliases: dict[tuple[str, str], str] = {}
        self.artifacts: dict[str, list[RegistryArtifact]] = {}  # `<experiment>/<run>/artifacts[/path]` -> its folder
        self.experiments: dict[str, str] = {}
        self.logged: dict[str, bytes] = {}  # `<run>/<path>` -> what was put in the artifacts
        self.calls: list[str] = []
        self.down = False
        self.fail_on: str | None = None
        self._prefix = prefix

    def _enter(self, call: str) -> None:
        self.calls.append(call)
        if self.down or self.fail_on == call:
            raise RegistryUnavailable("The models service does not answer")

    async def create_model(self, name: str) -> None:
        self._enter("create_model")
        if "/" in name or ":" in name or not name or len(name) > 256:
            raise RegistryRejected(f"Invalid model name {name!r}")
        if name in self.models:
            raise RegistryConflict
        self.models.add(name)

    async def model_exists(self, name: str) -> bool:
        self._enter("model_exists")
        return name in self.models

    async def delete_model(self, name: str) -> None:
        self._enter("delete_model")
        self.models.discard(name)
        for key in [key for key in self.versions if key[0] == name]:
            del self.versions[key]

    async def create_run(self, model_name: str) -> RegistryRun:
        self._enter("create_run")
        experiment = self.experiments.setdefault(model_name, str(len(self.experiments) + 1))
        run_id = uuid.uuid4().hex
        self.runs[run_id] = {"experiment": experiment, "status": "RUNNING"}
        return RegistryRun(experiment, run_id, f"mlflow-artifacts:/{experiment}/{run_id}/artifacts")

    async def log_artifact(self, run: RegistryRun, path: str, data: bytes) -> None:
        self._enter("log_artifact")
        self.logged[f"{run.run_id}/{path.strip('/')}"] = data

    async def finish_run(self, run_id: str, *, failed: bool = False) -> None:
        self._enter("finish_run")
        self.runs[run_id]["status"] = "FAILED" if failed else "FINISHED"

    async def delete_run(self, run_id: str) -> None:
        self._enter("delete_run")
        self.runs.pop(run_id, None)

    async def create_version(self, name: str, run: RegistryRun, path: str = "") -> RegistryVersion:
        self._enter("create_version")
        if name not in self.models:
            raise RegistryNotFound
        number = str(1 + sum(1 for key in self.versions if key[0] == name))
        source = f"{run.artifact_uri}/{path.strip('/')}" if path.strip("/") else run.artifact_uri
        version = RegistryVersion(name=name, version=number, run_id=run.run_id, source=source, status="READY")
        self.versions[(name, number)] = version
        return version

    async def get_version(self, name: str, version: str) -> RegistryVersion:
        self._enter("get_version")
        if (name, version) not in self.versions:
            raise RegistryNotFound
        return self.versions[(name, version)]

    async def delete_version(self, name: str, version: str) -> None:
        self._enter("delete_version")
        self.versions.pop((name, version), None)

    async def set_alias(self, name: str, alias: str, version: str) -> None:
        self._enter("set_alias")
        if (name, version) not in self.versions:
            raise RegistryNotFound
        self.aliases[(name, alias)] = version

    async def delete_alias(self, name: str, alias: str) -> None:
        self._enter("delete_alias")
        self.aliases.pop((name, alias), None)

    def _root(self, name: str, version: str) -> str:
        if (name, version) not in self.versions:
            raise RegistryNotFound
        return self.versions[(name, version)].source.removeprefix("mlflow-artifacts:/").strip("/")

    async def list_artifacts(self, name: str, version: str, path: str = "") -> list[RegistryArtifact]:
        self._enter("list_artifacts")
        root = self._root(name, version)
        return self.artifacts.get(f"{root}/{path.strip('/')}" if path.strip("/") else root, [])

    async def artifact_key_prefix(self, name: str, version: str) -> str:
        self._enter("artifact_key_prefix")
        return f"{self._prefix}{self._root(name, version)}/"


@pytest.fixture
def registry() -> Iterator[MemoryRegistry]:
    """MLflow, in memory, for the routes too: it is what `get_registry` answers while the test runs."""
    memory = MemoryRegistry()
    app.dependency_overrides[get_registry] = lambda: memory
    yield memory
    app.dependency_overrides.pop(get_registry, None)


@pytest.fixture
def store() -> Iterator[MemoryStore]:
    memory = MemoryStore()
    app.dependency_overrides[get_store] = lambda: memory
    yield memory
    app.dependency_overrides.pop(get_store, None)


@pytest.fixture(autouse=True)
def no_queue() -> Iterator[None]:
    """Nothing is queued in Redis by the tests: the versions are read by calling the processor."""
    app.dependency_overrides[get_jobs] = NoJobs
    yield
    app.dependency_overrides.pop(get_jobs, None)


@pytest.fixture
def as_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every request is the fixed dev user (AUTH_MODE=full-access): no identity provider needed."""
    monkeypatch.setattr(settings, "AUTH_MODE", "full-access")


@pytest.fixture
def login() -> Iterator[Callable[..., RequestContext]]:
    """Choose who is logged in: `login("u1", "ada")`, or `login(admin=True)`. Call it again to switch user."""

    def _login(user_id: str = "u1", username: str = "ada", admin: bool = False) -> RequestContext:
        user = RequestContext(user_id=user_id, username=username, name=username, is_admin=admin)
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    yield _login
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def client(db: AsyncSession, store: MemoryStore) -> AsyncIterator[httpx2.AsyncClient]:
    """The app over HTTP, on the test database and the in-memory store. Nobody is logged in until `login` is called."""
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
        yield client
