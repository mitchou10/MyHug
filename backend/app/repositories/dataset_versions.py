import uuid

from sqlalchemy import func, select, update

from app.models import Dataset, DatasetFile, DatasetVersion
from app.repositories.base import Repository


class DatasetVersionRepository(Repository):
    def add(self, version: DatasetVersion) -> None:
        self._db.add(version)

    def add_file(self, file: DatasetFile) -> None:
        self._db.add(file)

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
