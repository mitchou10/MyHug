import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Annotation, AnnotationLabel
from app.services.annotations import Progress, RowsToAnnotate, TaskView

Name = Annotated[str, Field(min_length=1, max_length=100)]
Description = Annotated[str, Field(max_length=1000)]


class LabelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    description: Description = ""


class LabelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    description: Description | None = None


class LabelOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    position: int

    @classmethod
    def of(cls, label: AnnotationLabel) -> "LabelOut":
        return cls(id=label.id, name=label.name, description=label.description, position=label.position)


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    type: Literal["classification"] = Field(description="The kind of answer. Others will come.")
    text_column: str = Field(min_length=1, max_length=200, description="The column that holds the text to annotate")
    labels: list[LabelIn] = Field(default_factory=list, max_length=200)


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    status: Literal["open", "closed"] | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    dataset: str = Field(description="`owner/name` of the dataset")
    name: str
    type: str
    status: str
    config: dict
    labels: list[LabelOut]
    created_by_username: str
    created_at: datetime
    can_edit: bool
    can_annotate: bool

    @classmethod
    def from_view(cls, view: TaskView) -> "TaskOut":
        t = view.task
        return cls(
            id=t.id,
            dataset=f"{view.dataset.owner}/{view.dataset.name}",
            name=t.name,
            type=t.type,
            status=t.status,
            config=t.config,
            labels=[LabelOut.of(label) for label in view.labels],
            created_by_username=t.created_by_username,
            created_at=t.created_at,
            can_edit=view.can_edit,
            can_annotate=view.can_annotate,
        )


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_id: uuid.UUID | None = None
    reason: str | None = Field(None, max_length=2000)
    status: Literal["draft", "submitted"] = "submitted"


class AnswerOut(BaseModel):
    split: str
    row_index: int
    status: str
    source: str
    label_id: uuid.UUID | None
    reason: str | None
    # The version of the dataset the answer was given on.
    version_number: int
    updated_at: datetime

    @classmethod
    def of(cls, a: Annotation) -> "AnswerOut":
        return cls(
            split=a.split,
            row_index=a.row_index,
            status=a.status,
            source=a.source,
            label_id=a.label_id,
            reason=a.reason,
            version_number=a.version_number,
            updated_at=a.updated_at,
        )


class RowOut(BaseModel):
    row_index: int
    text: str
    mine: AnswerOut | None


class RowsOut(BaseModel):
    split: str
    splits: list[str]
    total: int
    rows: list[RowOut]

    @classmethod
    def of(cls, page: RowsToAnnotate) -> "RowsOut":
        return cls(
            split=page.split,
            splits=page.splits,
            total=page.total,
            rows=[
                RowOut(row_index=r.row_index, text=r.text, mine=AnswerOut.of(r.mine) if r.mine else None)
                for r in page.rows
            ],
        )


class LabelCountOut(BaseModel):
    label_id: uuid.UUID
    answers: int


class ProgressOut(BaseModel):
    total: int = Field(description="Rows in the latest version of the dataset")
    mine: int = Field(description="Answers of the person who asks")
    mine_submitted: int
    answered_rows: int = Field(description="Rows that have at least one answer, from anybody")
    annotators: int
    by_label: list[LabelCountOut]

    @classmethod
    def of(cls, p: Progress) -> "ProgressOut":
        return cls(
            total=p.total,
            mine=p.mine,
            mine_submitted=p.submitted,
            answered_rows=p.answered_rows,
            annotators=p.annotators,
            by_label=[LabelCountOut(label_id=k, answers=v) for k, v in p.by_label.items()],
        )
