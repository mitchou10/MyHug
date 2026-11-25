import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.models import Annotation, AnnotationLabel, AnnotationTask, Dataset
from app.models.annotation import CLOSED, DRAFT, HUMAN, OPEN, SUBMITTED, TASK_TYPES
from app.models.dataset_member import ANNOTATOR
from app.repositories.annotations import AnnotationRepository
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services.actor import Actor
from app.services.dataset_access import EDITORS, DatasetAccess
from app.services.dataset_versions import DatasetVersionService, splits_of
from app.services.errors import (
    InvalidTask,
    LabelNotFound,
    NotAllowed,
    RowNotFound,
    TaskClosed,
    TaskNameTaken,
    TaskNotFound,
)

# The kinds of task that can be made today: the others are known (the list of the interface) but come later.
IMPLEMENTED = ("classification",)
# Who may answer: the people who may edit, and the members given the role of annotator.
ANNOTATORS = (*EDITORS, ANNOTATOR)
MAX_LABELS = 200
MAX_ROWS_PAGE = 100


@dataclass(frozen=True)
class TaskView:
    task: AnnotationTask
    dataset: Dataset
    labels: list[AnnotationLabel]
    # What the person who asks may do.
    can_edit: bool
    can_annotate: bool


@dataclass(frozen=True)
class RowToAnnotate:
    split: str
    row_index: int
    text: str
    # The answer of the person who asks, if there is one.
    mine: Annotation | None


@dataclass(frozen=True)
class RowsToAnnotate:
    split: str
    splits: list[str]
    total: int
    rows: list[RowToAnnotate]


@dataclass(frozen=True)
class Progress:
    total: int
    # What the person who asks answered, and how many rows have at least one answer, from anybody.
    mine: int
    submitted: int
    answered_rows: int
    annotators: int
    by_label: dict[uuid.UUID, int]


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _clean(name: str, what: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise InvalidTask(f"The {what} needs a name")
    return name


class AnnotationService:
    """The tasks of annotation of a dataset, their labels and the answers of the annotators.

    A task is made by the people who can edit the dataset; it is read by everybody who can read the dataset; it is
    answered by the people who can edit it and by its annotators. An answer is always the answer of one person to one
    row: the platform keeps what was said, never what someone else would conclude from it."""

    def __init__(
        self,
        access: DatasetAccess,
        datasets: DatasetRepository,
        annotations: AnnotationRepository,
        versions: DatasetVersionRepository,
        reading: DatasetVersionService,
        *,
        max_tasks: int,
    ) -> None:
        self._access = access
        self._datasets = datasets
        self._annotations = annotations
        self._versions = versions
        self._reading = reading
        self._max_tasks = max_tasks

    # ---- finding things

    async def _load(self, actor: Actor, task_id: uuid.UUID) -> tuple[AnnotationTask, Dataset, str | None]:
        task = await self._annotations.task(task_id)
        dataset = await self._datasets.get(task.dataset_id) if task else None
        if task is None or dataset is None:
            raise TaskNotFound
        role = await self._access.role(actor, dataset)
        if dataset.visibility != "public" and role is None:
            raise TaskNotFound  # a private dataset looks like it does not exist
        return task, dataset, role

    async def _view(self, task: AnnotationTask, dataset: Dataset, role: str | None) -> TaskView:
        return TaskView(
            task,
            dataset,
            await self._annotations.labels(task.id),
            can_edit=role in EDITORS,
            can_annotate=role in ANNOTATORS,
        )

    async def _editable(self, actor: Actor, task_id: uuid.UUID) -> tuple[AnnotationTask, Dataset]:
        task, dataset, role = await self._load(actor, task_id)
        if role not in EDITORS:
            raise NotAllowed
        return task, dataset

    # ---- tasks

    async def tasks(self, actor: Actor, owner: str, name: str) -> list[TaskView]:
        dataset, role = await self._access.get_readable(actor, owner, name)
        return [await self._view(task, dataset, role) for task in await self._annotations.tasks_of(dataset.id)]

    async def get(self, actor: Actor, task_id: uuid.UUID) -> TaskView:
        task, dataset, role = await self._load(actor, task_id)
        return await self._view(task, dataset, role)

    async def _text_columns(self, dataset: Dataset) -> list[str]:
        """The columns of the latest version, the same in every split of a dataset that is well made."""
        version = await self._versions.latest(dataset.id)
        if version is None:
            raise InvalidTask("This dataset has no rows yet")
        files = await self._versions.files(version.id)
        splits = splits_of(files)
        if not splits:
            raise InvalidTask("This dataset has no rows yet: its files may still be read")
        first = next(f for f in files if f.split == splits[0].name)
        return [c["name"] for c in first.columns]

    async def create(
        self,
        actor: Actor,
        owner: str,
        name: str,
        *,
        task_name: str,
        type: str,
        text_column: str,
        labels: list[tuple[str, str]],
    ) -> TaskView:
        dataset = await self._access.get_editable(actor, owner, name)
        if type not in TASK_TYPES or type not in IMPLEMENTED:
            raise InvalidTask(f"Tasks of type {type!r} cannot be made yet")
        task_name = _clean(task_name, "task")
        if await self._annotations.name_taken(dataset.id, task_name):
            raise TaskNameTaken
        if len(await self._annotations.tasks_of(dataset.id)) >= self._max_tasks:
            raise InvalidTask(f"A dataset has at most {self._max_tasks} tasks")
        if text_column not in await self._text_columns(dataset):
            raise InvalidTask(f"The dataset has no column {text_column!r}")
        cleaned = self._checked_labels(labels)
        task = AnnotationTask(
            dataset_id=dataset.id,
            name=task_name,
            type=type,
            config={"text_column": text_column},
            created_by=actor.user_id,
            created_by_username=actor.username,
        )
        self._annotations.add_task(task)
        await self._annotations.flush()
        for position, (label, description) in enumerate(cleaned):
            self._annotations.add_label(
                AnnotationLabel(task_id=task.id, name=label, description=description, position=position)
            )
        await self._annotations.commit()
        return await self._view(task, dataset, await self._access.role(actor, dataset))

    @staticmethod
    def _checked_labels(labels: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if len(labels) > MAX_LABELS:
            raise InvalidTask(f"A task has at most {MAX_LABELS} labels")
        cleaned = [(_clean(name, "label"), description.strip()) for name, description in labels]
        if len({name.lower() for name, _ in cleaned}) != len(cleaned):
            raise InvalidTask("Two labels have the same name")
        return cleaned

    async def update(self, actor: Actor, task_id: uuid.UUID, *, name: str | None, status: str | None) -> TaskView:
        task, dataset = await self._editable(actor, task_id)
        if name is not None:
            name = _clean(name, "task")
            if await self._annotations.name_taken(dataset.id, name, except_id=task.id):
                raise TaskNameTaken
            task.name = name
        if status is not None:
            if status not in (OPEN, CLOSED):
                raise InvalidTask("A task is open or closed")
            task.status = status
        await self._annotations.commit()
        return await self._view(task, dataset, await self._access.role(actor, dataset))

    async def delete(self, actor: Actor, task_id: uuid.UUID) -> None:
        """The task, its labels and all its answers."""
        task, _ = await self._editable(actor, task_id)
        await self._annotations.delete_task(task)
        await self._annotations.commit()

    # ---- labels

    async def add_label(self, actor: Actor, task_id: uuid.UUID, *, name: str, description: str) -> AnnotationLabel:
        task, _ = await self._editable(actor, task_id)
        name = _clean(name, "label")
        labels = await self._annotations.labels(task.id)
        if len(labels) >= MAX_LABELS:
            raise InvalidTask(f"A task has at most {MAX_LABELS} labels")
        if any(label.name.lower() == name.lower() for label in labels):
            raise InvalidTask("This task already has a label with this name")
        label = AnnotationLabel(
            task_id=task.id,
            name=name,
            description=description.strip(),
            position=max((label.position for label in labels), default=-1) + 1,
        )
        self._annotations.add_label(label)
        await self._annotations.commit()
        return label

    async def _label(self, task: AnnotationTask, label_id: uuid.UUID) -> AnnotationLabel:
        label = next((x for x in await self._annotations.labels(task.id) if x.id == label_id), None)
        if label is None:
            raise LabelNotFound
        return label

    async def update_label(
        self, actor: Actor, task_id: uuid.UUID, label_id: uuid.UUID, *, name: str | None, description: str | None
    ) -> AnnotationLabel:
        """Renaming a label changes no answer: they point to its id."""
        task, _ = await self._editable(actor, task_id)
        label = await self._label(task, label_id)
        if name is not None:
            name = _clean(name, "label")
            others = [x for x in await self._annotations.labels(task.id) if x.id != label.id]
            if any(x.name.lower() == name.lower() for x in others):
                raise InvalidTask("This task already has a label with this name")
            label.name = name
        if description is not None:
            label.description = description.strip()
        await self._annotations.commit()
        return label

    async def delete_label(self, actor: Actor, task_id: uuid.UUID, label_id: uuid.UUID) -> None:
        """Logical: the answers that use it keep it, it is no longer offered."""
        task, _ = await self._editable(actor, task_id)
        label = await self._label(task, label_id)
        label.deleted_at = datetime.now(UTC)
        await self._annotations.commit()

    # ---- rows and answers

    async def rows(
        self, actor: Actor, task_id: uuid.UUID, *, split: str | None, offset: int, limit: int
    ) -> RowsToAnnotate:
        task, dataset, _ = await self._load(actor, task_id)
        page = await self._reading.rows(
            actor,
            dataset.owner,
            dataset.name,
            split=split,
            number=None,
            offset=offset,
            limit=min(limit, MAX_ROWS_PAGE),
            query=None,
        )
        column = self._column_index(task, [c.name for c in page.columns])
        mine = await self._annotations.mine_in(task.id, actor.user_id, page.split, offset, offset + len(page.rows))
        rows = [
            RowToAnnotate(page.split, offset + i, str(row[column] or ""), mine.get(offset + i))
            for i, row in enumerate(page.rows)
        ]
        return RowsToAnnotate(page.split, page.splits, page.total, rows)

    @staticmethod
    def _column_index(task: AnnotationTask, columns: list[str]) -> int:
        column = task.config.get("text_column")
        if column not in columns:
            raise InvalidTask(f"The column {column!r} of this task is no longer in the dataset")
        return columns.index(column)

    async def _text_of(
        self, actor: Actor, task: AnnotationTask, dataset: Dataset, split: str, row: int
    ) -> tuple[str, int]:
        page = await self._reading.rows(
            actor, dataset.owner, dataset.name, split=split, number=None, offset=row, limit=1, query=None
        )
        if page.split != split or not page.rows:
            raise RowNotFound
        text = page.rows[0][self._column_index(task, [c.name for c in page.columns])]
        version = await self._versions.latest(dataset.id)
        return str(text or ""), version.number if version else 0

    async def answer(
        self,
        actor: Actor,
        task_id: uuid.UUID,
        split: str,
        row_index: int,
        *,
        label_id: uuid.UUID | None,
        reason: str | None,
        status: str,
    ) -> Annotation:
        """My answer to a row: made, or replaced (sending the same thing twice changes nothing)."""
        task, dataset, role = await self._load(actor, task_id)
        if role not in ANNOTATORS:
            raise NotAllowed
        if task.status != OPEN:
            raise TaskClosed
        if status not in (DRAFT, SUBMITTED):
            raise InvalidTask("An answer is a draft or submitted")
        if label_id is not None:
            await self._label(task, label_id)
        elif status == SUBMITTED:
            raise InvalidTask("A submitted answer needs a label")
        text, number = await self._text_of(actor, task, dataset, split, row_index)
        answer = await self._annotations.put(
            {
                "task_id": task.id,
                "split": split,
                "row_index": row_index,
                "annotator": actor.user_id,
                "annotator_username": actor.username,
                "version_number": number,
                "text_sha256": fingerprint(text),
                "status": status,
                "source": HUMAN,
                "label_id": label_id,
                "reason": (reason or "").strip() or None,
            }
        )
        await self._annotations.commit()
        return answer

    async def take_back(self, actor: Actor, task_id: uuid.UUID, split: str, row_index: int) -> None:
        task, _, role = await self._load(actor, task_id)
        if role not in ANNOTATORS:
            raise NotAllowed
        if task.status != OPEN:
            raise TaskClosed
        await self._annotations.remove(task.id, actor.user_id, split, row_index)
        await self._annotations.commit()

    async def progress(self, actor: Actor, task_id: uuid.UUID) -> Progress:
        task, dataset, _ = await self._load(actor, task_id)
        version = await self._versions.latest(dataset.id)
        total = sum(s.rows for s in splits_of(await self._versions.files(version.id))) if version else 0
        counts: Any = await self._annotations.counts(task.id, actor.user_id)
        mine, submitted, rows, people = counts
        return Progress(
            total=total,
            mine=mine,
            submitted=submitted,
            answered_rows=rows,
            annotators=people,
            by_label=await self._annotations.usage(task.id),
        )
