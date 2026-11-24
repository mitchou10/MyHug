import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update

from app.models import Dataset, DatasetFile, DatasetVersion
from app.models.dataset_version import FAILED, PENDING, PROCESSING
from app.repositories.base import Repository


class DatasetVersionRepository(Repository):
    def add(self, version: DatasetVersion) -> None:
        self._db.add(version)

    def add_file(self, file: DatasetFile) -> None:
        self._db.add(file)

    async def get_by_id(self, version_id: uuid.UUID) -> DatasetVersion | None:
        return await self._db.get(DatasetVersion, version_id)

    async def latest(self, dataset_id: uuid.UUID) -> DatasetVersion | None:
        result = await self._db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get(self, dataset_id: uuid.UUID, number: int) -> DatasetVersion | None:
        result = await self._db.execute(
            select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.number == number)
        )
        return result.scalar_one_or_none()

    async def history(self, dataset_id: uuid.UUID) -> list[DatasetVersion]:
        """The newest first."""
        result = await self._db.execute(
            select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(DatasetVersion.number.desc())
        )
        return list(result.scalars())

    async def files(self, version_id: uuid.UUID) -> list[DatasetFile]:
        result = await self._db.execute(
            select(DatasetFile).where(DatasetFile.version_id == version_id).order_by(DatasetFile.path)
        )
        return list(result.scalars())

    async def file(self, version_id: uuid.UUID, path: str) -> DatasetFile | None:
        result = await self._db.execute(
            select(DatasetFile).where(DatasetFile.version_id == version_id, DatasetFile.path == path)
        )
        return result.scalar_one_or_none()

    async def find_stored(self, dataset_id: uuid.UUID, sha256: str, size: int) -> DatasetFile | None:
        """A file of this dataset, in any version, that has this fingerprint and this size. Only a fingerprint a worker
        computed counts (a file sent in parts has none until it is read), not one that somebody announced."""
        result = await self._db.execute(
            select(DatasetFile)
            .join(DatasetVersion)
            .where(
                DatasetVersion.dataset_id == dataset_id, DatasetFile.sha256 == sha256, DatasetFile.size_bytes == size
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def storage_keys(self, dataset_id: uuid.UUID) -> set[str]:
        """Where the content of every file of every version is: what is to be removed with the dataset."""
        result = await self._db.execute(
            select(DatasetFile.storage_key)
            .join(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .distinct()
        )
        return set(result.scalars())

    async def count_downloads(self, dataset_id: uuid.UUID) -> None:
        await self._db.execute(update(Dataset).where(Dataset.id == dataset_id).values(downloads=Dataset.downloads + 1))

    async def count(self, dataset_id: uuid.UUID) -> int:
        result = await self._db.execute(
            select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
        )
        return result.scalar_one()

    # ---- for the worker

    async def claim(self, version_id: uuid.UUID, stale_before: datetime) -> DatasetVersion | None:
        """Takes a version in hand, for one worker only: it is `processing` from then on, and the attempt is counted.

        A version can be taken when it waits, when it failed (somebody asks to read it again), or when it has been
        `processing` for so long that its worker must have died. None when it is not up for the taking (ready, being
        read by another worker, or unknown)."""
        taken = await self._db.execute(
            update(DatasetVersion)
            .where(
                DatasetVersion.id == version_id,
                or_(
                    DatasetVersion.status.in_((PENDING, FAILED)),
                    and_(DatasetVersion.status == PROCESSING, DatasetVersion.processing_started_at < stale_before),
                ),
            )
            .values(
                status=PROCESSING, processing_started_at=func.now(), attempts=DatasetVersion.attempts + 1, error=None
            )
            .returning(DatasetVersion)
            .execution_options(populate_existing=True)
        )
        version = taken.scalar_one_or_none()
        await self._db.commit()  # the other workers see it at once
        return version

    async def release(self, version_id: uuid.UUID) -> None:
        """Puts a version back to waiting after a failure that is not its fault (the storage was down): it will be taken
        again."""
        await self._db.execute(
            update(DatasetVersion)
            .where(DatasetVersion.id == version_id, DatasetVersion.status == PROCESSING)
            .values(status=PENDING)
        )
        await self._db.commit()

    async def waiting(self, *, older_than: datetime, stale_before: datetime, limit: int) -> list[uuid.UUID]:
        """The versions nobody is reading: waiting for a while (the job that was to read them may have been lost), or
        being read by a worker that stopped answering."""
        result = await self._db.execute(
            select(DatasetVersion.id)
            .where(
                or_(
                    and_(DatasetVersion.status == PENDING, DatasetVersion.created_at < older_than),
                    and_(DatasetVersion.status == PROCESSING, DatasetVersion.processing_started_at < stale_before),
                )
            )
            .order_by(DatasetVersion.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def find_twin(self, dataset_id: uuid.UUID, sha256: str, size: int, key: str) -> DatasetFile | None:
        """A file of the dataset with the same content as this one but another object in the storage."""
        result = await self._db.execute(
            select(DatasetFile)
            .join(DatasetVersion)
            .where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetFile.sha256 == sha256,
                DatasetFile.size_bytes == size,
                DatasetFile.storage_key != key,
            )
            .order_by(DatasetFile.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def repoint(self, old_key: str, new_key: str) -> None:
        """Every file that was the object `old_key` is the object `new_key` from now on (they hold the same content)."""
        await self._db.execute(
            update(DatasetFile).where(DatasetFile.storage_key == old_key).values(storage_key=new_key)
        )
