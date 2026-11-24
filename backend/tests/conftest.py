import asyncio
import hashlib
import os
import uuid

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
from app.routers.deps import get_jobs  # noqa: E402
from app.storage import ObjectInfo, ObjectNotFound, PartInfo, StoredObject, get_store  # noqa: E402

SEEDED = ("feedback_types", "feedback_statuses")
RESET = (
    "TRUNCATE feedback_attachments, feedback_messages, feedbacks, feedback_types, feedback_statuses, "
    "user_profiles, notifications, dataset_likes, dataset_members, dataset_upload_files, dataset_uploads, "
    "dataset_files, dataset_versions, datasets"
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

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = StoredObject(data=data, content_type=content_type)

    async def get(self, key: str) -> StoredObject | None:
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def stream(self, key: str, chunk_size: int = 8 * 1024 * 1024) -> AsyncIterator[bytes]:
        stored = self.objects.get(key)
        if stored is None:
            raise ObjectNotFound(key)
        for start in range(0, len(stored.data), chunk_size):
            yield stored.data[start : start + chunk_size]

    async def head(self, key: str) -> ObjectInfo | None:
        stored = self.objects.get(key)
        return ObjectInfo(size=len(stored.data), content_type=stored.content_type) if stored else None

    async def create_multipart(self, key: str, content_type: str) -> str:
        upload_id = uuid.uuid4().hex
        self.uploads[upload_id] = {"key": key, "content_type": content_type, "parts": {}}
        return upload_id

    async def presign_part(self, key: str, upload_id: str, number: int, expires_in: int) -> str:
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

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        self.uploads.pop(upload_id, None)

    async def presign_get(
        self, key: str, expires_in: int, filename: str | None = None, *, internal: bool = False
    ) -> str:
        return f"memory://get/{key}"


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
