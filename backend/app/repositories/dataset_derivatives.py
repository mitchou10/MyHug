import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models import DatasetFile, DatasetFileDerivative
from app.models.dataset_derivative import FAILED, PARQUET, PENDING, PROCESSING, READY
from app.repositories.base import Repository


class DatasetDerivativeRepository(Repository):
    async def get_by_id(self, derivative_id: uuid.UUID) -> DatasetFileDerivative | None:
        return await self._db.get(DatasetFileDerivative, derivative_id)

    async def ready_for(self, source_keys: list[str], params_hash: str) -> dict[str, DatasetFileDerivative]:
        """The copies that can be read, by the storage key of their source."""
        if not source_keys:
            return {}
        result = await self._db.execute(
            select(DatasetFileDerivative).where(
                DatasetFileDerivative.source_storage_key.in_(source_keys),
                DatasetFileDerivative.kind == PARQUET,
                DatasetFileDerivative.params_hash == params_hash,
                DatasetFileDerivative.status == READY,
            )
        )
        return {item.source_storage_key: item for item in result.scalars()}

    async def create_missing(self, wanted: list[tuple[str, str, int]], params_hash: str) -> list[uuid.UUID]:
        """Makes the copies that do not exist yet, from (storage key, a path, size) of the sources. Returns the ones
        that are new. A copy that exists, in whatever state, is left alone: the sweep takes care of the ones that
        wait."""
        created: list[uuid.UUID] = []
        for key, path, size in wanted:
            result = await self._db.execute(
                insert(DatasetFileDerivative)
                .values(
                    id=uuid.uuid4(),
                    source_storage_key=key,
                    source_path=path,
                    source_size_bytes=size,
                    kind=PARQUET,
                    params_hash=params_hash,
                )
                .on_conflict_do_nothing(constraint="uq_dataset_file_derivatives_source")
                .returning(DatasetFileDerivative.id)
            )
            if (new := result.scalar_one_or_none()) is not None:
                created.append(new)
        return created

    async def source_rows(self, key: str) -> int | None:
        """How many rows the file with this storage key has, as counted when it was read."""
        result = await self._db.execute(
            select(DatasetFile.rows).where(DatasetFile.storage_key == key, DatasetFile.rows.is_not(None)).limit(1)
        )
        return result.scalar_one_or_none()

    # ---- for the worker

    async def claim(self, derivative_id: uuid.UUID, stale_before: datetime) -> DatasetFileDerivative | None:
        """Takes a copy in hand, for one worker only (see DatasetVersionRepository.claim)."""
        taken = await self._db.execute(
            update(DatasetFileDerivative)
            .where(
                DatasetFileDerivative.id == derivative_id,
                or_(
                    DatasetFileDerivative.status.in_((PENDING, FAILED)),
                    and_(
                        DatasetFileDerivative.status == PROCESSING,
                        DatasetFileDerivative.processing_started_at < stale_before,
                    ),
                ),
            )
            .values(
                status=PROCESSING,
                processing_started_at=func.now(),
                attempts=DatasetFileDerivative.attempts + 1,
                error=None,
            )
            .returning(DatasetFileDerivative)
            .execution_options(populate_existing=True)
        )
        derivative = taken.scalar_one_or_none()
        await self._db.commit()
        return derivative

    async def release(self, derivative_id: uuid.UUID) -> None:
        await self._db.execute(
            update(DatasetFileDerivative)
            .where(DatasetFileDerivative.id == derivative_id, DatasetFileDerivative.status == PROCESSING)
            .values(status=PENDING)
        )
        await self._db.commit()

    async def waiting(self, *, older_than: datetime, stale_before: datetime, limit: int) -> list[uuid.UUID]:
        result = await self._db.execute(
            select(DatasetFileDerivative.id)
            .where(
                or_(
                    and_(DatasetFileDerivative.status == PENDING, DatasetFileDerivative.created_at < older_than),
                    and_(
                        DatasetFileDerivative.status == PROCESSING,
                        DatasetFileDerivative.processing_started_at < stale_before,
                    ),
                )
            )
            .order_by(DatasetFileDerivative.created_at)
            .limit(limit)
        )
        return list(result.scalars())
