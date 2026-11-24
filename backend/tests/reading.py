"""What the worker does, played in the tests: it takes a version, reads its files and says what it found.
The real worker is another project (`worker/`); this one reads from the test storage in place of a signed address."""

import hashlib
import io
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DatasetVersion
from app.services import tables
from app.services.dataset_processing import FileRead
from app.services.errors import UnreadableDataFile
from app.services.factory import build_dataset_processing
from tests.conftest import MemoryStore


class Reader:
    def __init__(self, db: AsyncSession, store: MemoryStore) -> None:
        self._db, self._store = db, store
        self.service = build_dataset_processing(db, store)

    async def process(self, version_id: uuid.UUID) -> DatasetVersion | None:
        """The version as it ends up, or as it is when it was not up for the taking; None if there is none."""
        files = await self.service.claim(version_id)
        version = await self.service._versions.get_by_id(version_id)  # noqa: SLF001
        if files is None:
            return version
        read: list[FileRead] = []
        for file in files:
            stored = self._store.objects.get(file.url.removeprefix("memory://get/"))
            if stored is None:
                return await self.service.fail(version_id, f"{file.path} is missing from the storage")
            item = FileRead(id=file.id, size_bytes=len(stored.data))
            if file.needs_fingerprint:
                item = FileRead(id=file.id, size_bytes=len(stored.data), sha256=hashlib.sha256(stored.data).hexdigest())
            if file.needs_rows:
                try:
                    info = tables.inspect(file.path, io.BytesIO(stored.data))
                except UnreadableDataFile as error:
                    return await self.service.fail(version_id, str(error))
                item = FileRead(item.id, item.size_bytes, item.sha256, info.rows, info.columns)
            read.append(item)
        return await self.service.complete(version_id, read)
