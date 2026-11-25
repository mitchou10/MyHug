import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update

from app.models import Dataset, ModelEvaluation
from app.models.model_evaluation import PENDING, RUNNING, UPLOADING
from app.repositories.base import Repository
from app.repositories.datasets import visible_to


class ModelEvaluationRepository(Repository):
    def add(self, evaluation: ModelEvaluation) -> None:
        self._db.add(evaluation)

    async def get(self, model_id: uuid.UUID, evaluation_id: uuid.UUID) -> ModelEvaluation | None:
        """Looked up with its model: the evaluation of another model finds nothing."""
        result = await self._db.execute(
            select(ModelEvaluation).where(ModelEvaluation.id == evaluation_id, ModelEvaluation.model_id == model_id)
        )
        return result.scalar_one_or_none()

    async def page(
        self, model_id: uuid.UUID, *, task: str | None, version: int | None, limit: int, offset: int
    ) -> list[ModelEvaluation]:
        query = select(ModelEvaluation).where(ModelEvaluation.model_id == model_id)
        if task is not None:
            query = query.where(ModelEvaluation.task == task)
        if version is not None:
            query = query.where(ModelEvaluation.version_number == version)
        result = await self._db.execute(
            query.order_by(ModelEvaluation.created_at.desc(), ModelEvaluation.id).limit(limit).offset(offset)
        )
        return list(result.scalars())

    async def count_open(self, model_id: uuid.UUID) -> int:
        """How many are going to the storage, waiting for a worker, or being computed."""
        result = await self._db.execute(
            select(func.count())
            .select_from(ModelEvaluation)
            .where(ModelEvaluation.model_id == model_id, ModelEvaluation.status.in_((UPLOADING, PENDING, RUNNING)))
        )
        return result.scalar_one()

    async def delete(self, evaluation: ModelEvaluation) -> None:
        await self._db.delete(evaluation)

    async def uploading_until(self, now: datetime) -> list[ModelEvaluation]:
        """The evaluations whose predictions did not finish going to the storage in time."""
        result = await self._db.execute(
            select(ModelEvaluation).where(ModelEvaluation.status == UPLOADING, ModelEvaluation.expires_at <= now)
        )
        return list(result.scalars())

    async def readable_datasets(self, ids: set[uuid.UUID], user_id: str, is_admin: bool) -> set[uuid.UUID]:
        """Which of these datasets the person may read: an evaluation tells the address of its dataset only to them."""
        if not ids:
            return set()
        result = await self._db.execute(select(Dataset.id).where(Dataset.id.in_(ids), visible_to(user_id, is_admin)))
        return set(result.scalars())

    # ---- the worker that computes

    async def by_id(self, evaluation_id: uuid.UUID) -> ModelEvaluation | None:
        return await self._db.get(ModelEvaluation, evaluation_id)

    async def claim(self, evaluation_id: uuid.UUID, stale_before: datetime) -> ModelEvaluation | None:
        """Takes an evaluation in hand, for one worker only: it is `running` from then on, and the attempt is counted.

        It can be taken when it waits, or when it has been `running` for so long that its worker must have died. None
        when it is not up for the taking."""
        taken = await self._db.execute(
            update(ModelEvaluation)
            .where(
                ModelEvaluation.id == evaluation_id,
                or_(
                    ModelEvaluation.status == PENDING,
                    and_(ModelEvaluation.status == RUNNING, ModelEvaluation.processing_started_at < stale_before),
                ),
            )
            .values(
                status=RUNNING,
                processing_started_at=func.now(),
                attempts=ModelEvaluation.attempts + 1,
                error=None,
            )
            .returning(ModelEvaluation)
            .execution_options(populate_existing=True)
        )
        evaluation = taken.scalar_one_or_none()
        await self._db.commit()  # the other workers see it at once
        return evaluation

    async def release(self, evaluation_id: uuid.UUID) -> None:
        """Back to waiting after a failure that is not the data's fault (the storage was down)."""
        await self._db.execute(
            update(ModelEvaluation)
            .where(ModelEvaluation.id == evaluation_id, ModelEvaluation.status == RUNNING)
            .values(status=PENDING)
        )
        await self._db.commit()

    async def waiting(self, *, older_than: datetime, stale_before: datetime, limit: int) -> list[uuid.UUID]:
        """The evaluations nobody is computing: waiting for a while (the job may have been lost), or being computed by
        a worker that stopped answering."""
        result = await self._db.execute(
            select(ModelEvaluation.id)
            .where(
                or_(
                    and_(ModelEvaluation.status == PENDING, ModelEvaluation.created_at < older_than),
                    and_(ModelEvaluation.status == RUNNING, ModelEvaluation.processing_started_at < stale_before),
                )
            )
            .order_by(ModelEvaluation.created_at)
            .limit(limit)
        )
        return list(result.scalars())
