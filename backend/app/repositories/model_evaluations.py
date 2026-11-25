import uuid

from sqlalchemy import select

from app.models import Dataset, ModelEvaluation
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

    async def delete(self, evaluation: ModelEvaluation) -> None:
        await self._db.delete(evaluation)

    async def readable_datasets(self, ids: set[uuid.UUID], user_id: str, is_admin: bool) -> set[uuid.UUID]:
        """Which of these datasets the person may read: an evaluation tells the address of its dataset only to them."""
        if not ids:
            return set()
        result = await self._db.execute(select(Dataset.id).where(Dataset.id.in_(ids), visible_to(user_id, is_admin)))
        return set(result.scalars())
