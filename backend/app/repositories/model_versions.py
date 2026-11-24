import uuid
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update

from app.models import Model, ModelFile, ModelVersion
from app.models.model_version import FAILED, PENDING, PROCESSING, RESOLVING, UNRESOLVED
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

    # ---- for the worker

    async def claim(self, version_id: uuid.UUID, stale_before: datetime) -> ModelVersion | None:
        """Takes a version in hand, for one worker only: it is `processing` from then on, and the attempt is counted.

        A version can be taken when it waits, when it failed (somebody asks to check it again), or when it has been
        `processing` for so long that its worker must have died. None when it is not up for the taking."""
        taken = await self._db.execute(
            update(ModelVersion)
            .where(
                ModelVersion.id == version_id,
                or_(
                    ModelVersion.status.in_((PENDING, FAILED)),
                    and_(ModelVersion.status == PROCESSING, ModelVersion.processing_started_at < stale_before),
                ),
            )
            .values(status=PROCESSING, processing_started_at=func.now(), attempts=ModelVersion.attempts + 1, error=None)
            .returning(ModelVersion)
            .execution_options(populate_existing=True)
        )
        version = taken.scalar_one_or_none()
        await self._db.commit()  # the other workers see it at once
        return version

    async def release(self, version_id: uuid.UUID) -> None:
        """Back to waiting after a failure that is not its fault (the storage was down): it will be taken again."""
        await self._db.execute(
            update(ModelVersion)
            .where(ModelVersion.id == version_id, ModelVersion.status == PROCESSING)
            .values(status=PENDING)
        )
        await self._db.commit()

    async def waiting(self, *, older_than: datetime, stale_before: datetime, limit: int) -> list[uuid.UUID]:
        """The versions nobody is checking: waiting for a while (the job may have been lost), or being checked by a
        worker that stopped answering."""
        result = await self._db.execute(
            select(ModelVersion.id)
            .where(
                or_(
                    and_(ModelVersion.status == PENDING, ModelVersion.created_at < older_than),
                    and_(ModelVersion.status == PROCESSING, ModelVersion.processing_started_at < stale_before),
                )
            )
            .order_by(ModelVersion.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def find_twin(self, model_id: uuid.UUID, sha256: str, size: int, key: str) -> ModelFile | None:
        """A file of the model with the same content as this one but another object in the storage."""
        result = await self._db.execute(
            select(ModelFile)
            .join(ModelVersion)
            .where(
                ModelVersion.model_id == model_id,
                ModelFile.sha256 == sha256,
                ModelFile.size_bytes == size,
                ModelFile.storage_key != key,
            )
            .order_by(ModelFile.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def repoint(self, old_key: str, new_key: str) -> None:
        """Every file that was the object `old_key` is the object `new_key` from now on (they hold the same content)."""
        await self._db.execute(update(ModelFile).where(ModelFile.storage_key == old_key).values(storage_key=new_key))

    # ---- for the worker: the code a version points to

    async def claim_code(self, version_id: uuid.UUID, stale_before: datetime) -> ModelVersion | None:
        """Takes the code of a version in hand, for one worker only: it is `resolving` from then on, and the attempt is
        counted. Only code that is not resolved can be taken (or that a worker was resolving for so long that it must
        have died): a commit that was found is never looked for again."""
        taken = await self._db.execute(
            update(ModelVersion)
            .where(
                ModelVersion.id == version_id,
                or_(
                    ModelVersion.code_state == UNRESOLVED,
                    and_(ModelVersion.code_state == RESOLVING, ModelVersion.code_started_at < stale_before),
                ),
            )
            .values(code_state=RESOLVING, code_started_at=func.now(), code_attempts=ModelVersion.code_attempts + 1)
            .returning(ModelVersion)
            .execution_options(populate_existing=True)
        )
        version = taken.scalar_one_or_none()
        await self._db.commit()  # the other workers see it at once
        return version

    async def release_code(self, version_id: uuid.UUID) -> None:
        """Back to waiting after a failure that is not its fault (the host was down, or limited the calls)."""
        await self._db.execute(
            update(ModelVersion)
            .where(ModelVersion.id == version_id, ModelVersion.code_state == RESOLVING)
            .values(code_state=UNRESOLVED)
        )
        await self._db.commit()

    async def waiting_code(self, *, older_than: datetime, stale_before: datetime, limit: int) -> list[uuid.UUID]:
        """The code nobody is resolving: waiting for a while (the job may have been lost), or being resolved by a worker
        that stopped answering."""
        result = await self._db.execute(
            select(ModelVersion.id)
            .where(
                or_(
                    and_(ModelVersion.code_state == UNRESOLVED, ModelVersion.created_at < older_than),
                    and_(ModelVersion.code_state == RESOLVING, ModelVersion.code_started_at < stale_before),
                )
            )
            .order_by(ModelVersion.created_at)
            .limit(limit)
        )
        return list(result.scalars())
