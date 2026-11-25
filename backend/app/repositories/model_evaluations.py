import uuid
from datetime import datetime

from sqlalchemy import func, select

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
