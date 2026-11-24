import uuid

from sqlalchemy import delete, func, select, update

from app.models import Model, ModelFile, ModelVersion
from app.repositories.base import Repository


class ModelVersionRepository(Repository):
    def add(self, version: ModelVersion) -> None:
        self._db.add(version)

    def add_file(self, file: ModelFile) -> None:
        self._db.add(file)

    async def latest(self, model_id: uuid.UUID) -> ModelVersion | None:
        result = await self._db.execute(
            select(ModelVersion).where(ModelVersion.model_id == model_id).order_by(ModelVersion.number.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def get(self, model_id: uuid.UUID, number: int) -> ModelVersion | None:
        result = await self._db.execute(
            select(ModelVersion).where(ModelVersion.model_id == model_id, ModelVersion.number == number)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, version_id: uuid.UUID) -> ModelVersion | None:
        return await self._db.get(ModelVersion, version_id)

    async def history(self, model_id: uuid.UUID) -> list[ModelVersion]:
        """The versions of a model, the newest first."""
        result = await self._db.execute(
            select(ModelVersion).where(ModelVersion.model_id == model_id).order_by(ModelVersion.number.desc())
        )
        return list(result.scalars())

    async def next_number(self, model_id: uuid.UUID) -> int:
        result = await self._db.execute(
            select(func.coalesce(func.max(ModelVersion.number), 0)).where(ModelVersion.model_id == model_id)
        )
        return result.scalar_one() + 1

    async def files(self, version_id: uuid.UUID) -> list[ModelFile]:
        result = await self._db.execute(
            select(ModelFile).where(ModelFile.version_id == version_id).order_by(ModelFile.path)
        )
        return list(result.scalars())

    async def file(self, version_id: uuid.UUID, path: str) -> ModelFile | None:
        result = await self._db.execute(
            select(ModelFile).where(ModelFile.version_id == version_id, ModelFile.path == path)
        )
        return result.scalar_one_or_none()

    async def find_stored(self, model_id: uuid.UUID, sha256: str, size: int) -> ModelFile | None:
        """A file of this model that is exactly this one: same fingerprint (one a worker computed, never one a browser
        announced) and same size. Only within the model: a fingerprint is no proof of what somebody else may read."""
        result = await self._db.execute(
            select(ModelFile)
            .join(ModelVersion)
            .where(ModelVersion.model_id == model_id, ModelFile.sha256 == sha256, ModelFile.size_bytes == size)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def keys_of(self, version_id: uuid.UUID) -> set[str]:
        result = await self._db.execute(select(ModelFile.storage_key).where(ModelFile.version_id == version_id))
        return set(result.scalars())

    async def keys_kept_by_others(self, model_id: uuid.UUID, version_id: uuid.UUID, keys: set[str]) -> set[str]:
        """Which of `keys` another version of the model still points to."""
        if not keys:
            return set()
        result = await self._db.execute(
            select(ModelFile.storage_key)
            .join(ModelVersion)
            .where(ModelVersion.model_id == model_id, ModelVersion.id != version_id, ModelFile.storage_key.in_(keys))
            .distinct()
        )
        return set(result.scalars())

    async def delete(self, version_id: uuid.UUID) -> None:
        """Its files go with it (the database cascades)."""
        await self._db.execute(delete(ModelVersion).where(ModelVersion.id == version_id))

    async def set_latest(self, model_id: uuid.UUID) -> None:
        """Copies what the latest version holds onto the model (0 and 0 when there is none), for the lists."""
        latest = await self.latest(model_id)
        size = (
            0
            if latest is None
            else (
                await self._db.execute(
                    select(func.coalesce(func.sum(ModelFile.size_bytes), 0)).where(ModelFile.version_id == latest.id)
                )
            ).scalar_one()
        )
        await self._db.execute(
            update(Model)
            .where(Model.id == model_id)
            .values(version=latest.number if latest else 0, size_bytes=size, updated_at=func.now())
        )

    async def count_downloads(self, model_id: uuid.UUID) -> None:
        await self._db.execute(update(Model).where(Model.id == model_id).values(downloads=Model.downloads + 1))
