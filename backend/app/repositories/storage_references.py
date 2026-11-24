import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import delete, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import DatasetFile, DatasetFileDerivative, DatasetUpload, DatasetUploadFile
from app.models.dataset_upload import OPEN
from app.repositories.base import Repository

# Any number: the same everywhere, so that two runs of the collector see each other.
LOCK = 7_243_001


class StorageReferenceRepository(Repository):
    """What the database says about the objects of the storage: which of them something points to."""

    @asynccontextmanager
    async def exclusive(self) -> AsyncGenerator[bool]:
        """One collection at a time. True when this one holds the lock; False when another is running. The lock belongs
        to a connection of its own, held for the time of the collection (the session of the request commits and gives
        its connection back; a lock left on a connection in the pool would never be freed)."""
        bind = self._db.bind
        assert bind is not None
        engine = bind.engine if isinstance(bind, AsyncConnection) else bind
        async with engine.connect() as connection:
            got = bool((await connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK})).scalar())
            try:
                yield got
            finally:
                if got:
                    await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK})

    async def referenced(self, keys: list[str]) -> set[str]:
        """The keys among `keys` that something points to: a file of a version (of any dataset), a file of an upload
        that is still going on, or a copy."""
        if not keys:
            return set()
        found: set[str] = set()
        queries = (
            select(DatasetFile.storage_key).where(DatasetFile.storage_key.in_(keys)),
            select(DatasetUploadFile.storage_key)
            .join(DatasetUpload, DatasetUpload.id == DatasetUploadFile.upload_id)
            .where(DatasetUpload.status == OPEN, DatasetUploadFile.storage_key.in_(keys)),
            select(DatasetFileDerivative.storage_key).where(DatasetFileDerivative.storage_key.in_(keys)),
        )
        for query in queries:
            found.update((await self._db.execute(query)).scalars())
        return found

    async def orphan_copies(self, older_than: datetime, limit: int) -> list[DatasetFileDerivative]:
        """The copies whose source no file of any version holds any more, and that were not touched for a while."""
        result = await self._db.execute(
            select(DatasetFileDerivative)
            .where(
                DatasetFileDerivative.updated_at < older_than,
                ~exists().where(DatasetFile.storage_key == DatasetFileDerivative.source_storage_key),
            )
            .limit(limit)
        )
        return list(result.scalars())

    async def delete_copies(self, ids: list[uuid.UUID]) -> None:
        await self._db.execute(delete(DatasetFileDerivative).where(DatasetFileDerivative.id.in_(ids)))

    async def owned_uploads(self) -> set[str]:
        """The identifiers of the uploads in parts that something owns: an upload that is open, a copy being written."""
        sessions = await self._db.execute(
            select(DatasetUploadFile.multipart_id)
            .join(DatasetUpload, DatasetUpload.id == DatasetUploadFile.upload_id)
            .where(DatasetUpload.status == OPEN, DatasetUploadFile.multipart_id.is_not(None))
        )
        copies = await self._db.execute(
            select(DatasetFileDerivative.multipart_id).where(DatasetFileDerivative.multipart_id.is_not(None))
        )
        return {item for item in (*sessions.scalars(), *copies.scalars()) if item}

    async def sample_keys(self, count: int) -> list[str]:
        """Keys of files of versions, taken at random: to check that their objects are there."""
        keys = select(DatasetFile.storage_key).distinct().subquery()
        result = await self._db.execute(select(keys.c.storage_key).order_by(func.random()).limit(count))
        return list(result.scalars())
