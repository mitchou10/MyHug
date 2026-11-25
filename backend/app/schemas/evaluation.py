import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.services.model_evaluations import EvaluationView

MetricId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,40}$")]
Address = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=201)
]


# A number, not a boolean or a text, and not nan or infinity.
Value = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class MetricOut(BaseModel):
    id: str
    name: str
    # Whether a higher value is better (an error is not).
    higher: bool
    # The main metric of the task.
    primary: bool


class TaskMetricsOut(BaseModel):
    task: str
    metrics: list[MetricOut]
    # What is shown to the others unless the author chooses.
    default_shown: list[str]


class EvaluationIn(BaseModel):
    """The result of an evaluation that was computed somewhere else. It is kept as **sent**, never as measured."""

    version: int = Field(ge=1, description="The number of the version of the model that was evaluated")
    task: str = Field(max_length=40)
    results: dict[MetricId, Value] = Field(
        description="`{metric id: value}`, the metrics of the task (see `GET /api/metrics`), finite numbers"
    )
    shown: list[MetricId] | None = Field(
        None, max_length=50, description="The metrics the others see. Empty: the main metric and the next one"
    )
    dataset: Address | None = Field(None, description="`owner/name` of a dataset you can read")
    dataset_version: int | None = Field(None, ge=1)
    split: str | None = Field(None, max_length=50)
    input_column: str | None = Field(None, max_length=255)
    target_column: str | None = Field(None, max_length=255)
    items: int | None = Field(None, ge=0, description="How many items it was computed on")
    note: str = Field("", max_length=1000, description="How it was obtained")


class ShownIn(BaseModel):
    shown: list[MetricId] = Field(max_length=50)


class EvaluationOut(BaseModel):
    id: uuid.UUID
    version: int
    task: str
    # The address of the dataset, only for a person who may read it.
    dataset: str | None
    dataset_version: int | None
    split: str | None
    input_column: str | None
    target_column: str | None
    items: int | None
    # `measured`: the platform computed it. `submitted`: a person sent it and nothing says how it was obtained.
    source: Literal["measured", "submitted"]
    status: Literal["pending", "running", "done", "failed", "stopped"]
    error: str | None
    # The metrics this person sees: all of them for the people who can edit the model, the chosen ones for the others.
    results: dict[str, float]
    # How many were left out for this person.
    hidden: int
    shown: list[str]
    note: str
    created_by_username: str
    created_at: datetime
    finished_at: datetime | None
    # Whether this person may change or delete it.
    can_edit: bool

    @classmethod
    def from_view(cls, view: EvaluationView) -> "EvaluationOut":
        e = view.evaluation
        return cls(
            id=e.id,
            version=e.version_number,
            task=e.task,
            dataset=view.dataset,
            dataset_version=e.dataset_version if view.dataset else None,
            split=e.split,
            input_column=e.input_column,
            target_column=e.target_column,
            items=e.items,
            source=e.source,  # ty: ignore[invalid-argument-type]
            status=e.status,  # ty: ignore[invalid-argument-type]
            error=e.error,
            results=view.results,
            hidden=view.hidden,
            shown=e.shown if view.can_edit else [m for m in e.shown if m in view.results],
            note=e.note,
            created_by_username=e.created_by_username,
            created_at=e.created_at,
            finished_at=e.finished_at,
            can_edit=view.can_edit,
        )
