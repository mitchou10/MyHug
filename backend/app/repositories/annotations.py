import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import Annotation, AnnotationLabel, AnnotationTask
from app.repositories.base import Repository


class AnnotationRepository(Repository):
    # ---- tasks

    def add_task(self, task: AnnotationTask) -> None:
        self._db.add(task)

    async def task(self, task_id: uuid.UUID) -> AnnotationTask | None:
        return await self._db.get(AnnotationTask, task_id)

    async def tasks_of(self, dataset_id: uuid.UUID) -> list[AnnotationTask]:
        result = await self._db.execute(
            select(AnnotationTask)
            .where(AnnotationTask.dataset_id == dataset_id)
            .order_by(AnnotationTask.created_at, AnnotationTask.id)
        )
        return list(result.scalars())

    async def name_taken(self, dataset_id: uuid.UUID, name: str, *, except_id: uuid.UUID | None = None) -> bool:
        query = (
            select(func.count())
            .select_from(AnnotationTask)
            .where(AnnotationTask.dataset_id == dataset_id, AnnotationTask.name == name)
        )
        if except_id is not None:
            query = query.where(AnnotationTask.id != except_id)
        return (await self._db.execute(query)).scalar_one() > 0

    async def delete_task(self, task: AnnotationTask) -> None:
        await self._db.delete(task)

    # ---- labels

    def add_label(self, label: AnnotationLabel) -> None:
        self._db.add(label)

    async def labels(self, task_id: uuid.UUID, *, with_deleted: bool = False) -> list[AnnotationLabel]:
        query = select(AnnotationLabel).where(AnnotationLabel.task_id == task_id)
        if not with_deleted:
            query = query.where(AnnotationLabel.deleted_at.is_(None))
        result = await self._db.execute(query.order_by(AnnotationLabel.position, AnnotationLabel.id))
        return list(result.scalars())

    async def usage(self, task_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """How many answers use each label of a task."""
        result = await self._db.execute(
            select(Annotation.label_id, func.count())
            .where(Annotation.task_id == task_id, Annotation.label_id.is_not(None))
            .group_by(Annotation.label_id)
        )
        return {label_id: count for label_id, count in result.all() if label_id is not None}

    # ---- answers

    async def mine(self, task_id: uuid.UUID, annotator: str, split: str, row_index: int) -> Annotation | None:
        result = await self._db.execute(
            select(Annotation).where(
                Annotation.task_id == task_id,
                Annotation.annotator == annotator,
                Annotation.split == split,
                Annotation.row_index == row_index,
            )
        )
        return result.scalar_one_or_none()

    async def put(self, values: dict) -> Annotation:
        """My answer to a row: made, or replaced. The same call twice gives the same answer."""
        keys = ["task_id", "split", "row_index", "annotator"]
        changed = {k: v for k, v in values.items() if k not in keys}
        result = await self._db.execute(
            pg_insert(Annotation)
            .values(**values)
            .on_conflict_do_update(constraint="uq_annotations_row", set_=changed)
            .returning(Annotation)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def remove(self, task_id: uuid.UUID, annotator: str, split: str, row_index: int) -> bool:
        removed = await self._db.execute(
            delete(Annotation)
            .where(
                Annotation.task_id == task_id,
                Annotation.annotator == annotator,
                Annotation.split == split,
                Annotation.row_index == row_index,
            )
            .returning(Annotation.id)
        )
        return removed.first() is not None

    async def mine_in(
        self, task_id: uuid.UUID, annotator: str, split: str, start: int, stop: int
    ) -> dict[int, Annotation]:
        """My answers to the rows [start, stop) of a split, by row."""
        result = await self._db.execute(
            select(Annotation).where(
                Annotation.task_id == task_id,
                Annotation.annotator == annotator,
                Annotation.split == split,
                Annotation.row_index >= start,
                Annotation.row_index < stop,
            )
        )
        return {a.row_index: a for a in result.scalars()}

    async def counts(self, task_id: uuid.UUID, annotator: str) -> tuple[int, int, int, int]:
        """My answers, those of them that are submitted, the rows that have at least one answer, and how many people
        answered."""
        mine = await self._db.execute(
            select(func.count(), func.count().filter(Annotation.status == "submitted")).where(
                Annotation.task_id == task_id, Annotation.annotator == annotator
            )
        )
        rows = await self._db.execute(
            select(func.count()).select_from(
                select(Annotation.split, Annotation.row_index)
                .where(Annotation.task_id == task_id)
                .distinct()
                .subquery()
            )
        )
        people = await self._db.execute(
            select(func.count(func.distinct(Annotation.annotator))).where(Annotation.task_id == task_id)
        )
        done, submitted = mine.one()
        return done, submitted, rows.scalar_one(), people.scalar_one()
