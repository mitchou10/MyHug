import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.dataset import PartOut
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


Format = Literal["jsonl", "csv", "parquet"]
Seconds = Annotated[float, Field(ge=0, le=10_000_000, allow_inf_nan=False)]


class GpuIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    memory_gb: float | None = Field(None, ge=0, le=100_000, allow_inf_nan=False)


class HardwareIn(BaseModel):
    """What the predictions were made on. For predictions a person sent: what they say, the platform cannot check."""

    model_config = ConfigDict(extra="forbid")

    device: Literal["cpu", "gpu", "tpu", "other"]
    cpu: str | None = Field(None, max_length=200, description="The model of the processor")
    cpu_cores: int | None = Field(None, ge=1, le=4096)
    ram_gb: float | None = Field(None, ge=0, le=1_000_000, allow_inf_nan=False)
    gpus: list[GpuIn] = Field(default_factory=list, max_length=16)
    os: str | None = Field(None, max_length=100)
    runtime: str | None = Field(None, max_length=300, description="What ran the model: `onnxruntime 1.20, python 3.13`")


class InferenceIn(BaseModel):
    """How the predictions were made: how long it took, and on what."""

    model_config = ConfigDict(extra="forbid")

    seconds: Seconds | None = Field(None, description="The time the model took to make all the predictions")
    hardware: HardwareIn | None = None


class GpuOut(BaseModel):
    name: str
    memory_gb: float | None


class HardwareOut(BaseModel):
    """What the predictions were made on (plain values: what was checked going in is not checked again)."""

    device: Literal["cpu", "gpu", "tpu", "other"]
    cpu: str | None
    cpu_cores: int | None
    ram_gb: float | None
    gpus: list[GpuOut]
    os: str | None
    runtime: str | None


class InferenceOut(BaseModel):
    seconds: float | None
    # The time for one item, in milliseconds: only when the number of items is known (the worker counts them).
    ms_per_item: float | None
    hardware: HardwareOut | None
    # `declared`: what the person who sent the predictions says. `measured`: what the platform measured when it ran the
    # model itself.
    origin: Literal["declared", "measured"]


class EvaluationStartIn(BaseModel):
    """An evaluation to start: which model version, on which part of which dataset, and the predictions that will be
    sent to compare with it. The platform computes the metrics; a person never sends one."""

    version: int = Field(ge=1, description="The number of the version of the model that was evaluated")
    task: str = Field(max_length=40)
    dataset: Address = Field(description="`owner/name` of a dataset you can read: what the predictions are compared to")
    dataset_version: int | None = Field(None, ge=1, description="Empty: the latest version")
    split: str = Field(max_length=50, description="`train`, `test`... one of the splits of the dataset")
    target_column: str = Field(max_length=255, description="The column of the dataset that holds the right answer")
    key_column: str | None = Field(
        None,
        max_length=255,
        description="A column of the dataset that identifies each item, also in the file of predictions. "
        "Empty: the line of the file is the position of the item in the split, from 0",
    )
    input_column: str | None = Field(None, max_length=255, description="The column the model read, for the record")
    prediction_column: str = Field(
        "prediction", max_length=255, description="The column of the file with the prediction"
    )
    format: Format
    size: int = Field(gt=0, description="The size of the file of predictions, in bytes")
    note: str = Field("", max_length=1000, description="How the predictions were obtained")
    inference: InferenceIn | None = Field(None, description="How long it took and on what: what you say, not checked")


class UploadStateOut(BaseModel):
    """Where the predictions are going."""

    status: str
    # The size of the file that was announced: a file that is not this size is not the one to send.
    size_bytes: int | None
    part_size: int | None
    parts_count: int | None
    expires_at: datetime | None
    # The parts that reached the storage, only when asked, to go on after an interruption.
    received: list[PartOut] | None = None


class PartsRequest(BaseModel):
    numbers: list[int] = Field(min_length=1, max_length=100, description="The numbers of the parts, from 1")


class ShownIn(BaseModel):
    shown: list[MetricId] = Field(max_length=50)


def _hardware(stored: dict | None) -> "HardwareOut | None":
    if not stored:
        return None
    return HardwareOut(
        device=stored["device"],
        cpu=stored.get("cpu"),
        cpu_cores=stored.get("cpu_cores"),
        ram_gb=stored.get("ram_gb"),
        gpus=[GpuOut(name=g["name"], memory_gb=g.get("memory_gb")) for g in stored.get("gpus", [])],
        os=stored.get("os"),
        runtime=stored.get("runtime"),
    )


def _inference(e) -> "InferenceOut | None":
    if not e.inference:
        return None
    seconds = e.inference.get("seconds")
    per_item = seconds * 1000 / e.items if seconds is not None and e.items else None
    return InferenceOut(
        seconds=seconds,
        ms_per_item=per_item,
        hardware=_hardware(e.inference.get("hardware")),
        origin="measured" if e.source == "inference" else "declared",
    )


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
    # Where the predictions come from: `predictions` (a person sent them), `endpoint` (the platform called the model
    # that is served), `inference` (the platform ran it). The platform computes the metrics in every case.
    source: Literal["predictions", "endpoint", "inference"]
    status: Literal["uploading", "pending", "running", "done", "failed", "stopped"]
    predictions_format: str | None
    predictions_size: int | None
    key_column: str | None
    prediction_column: str
    error: str | None
    # The metrics this person sees: all of them for the people who can edit the model, the chosen ones for the others.
    results: dict[str, float]
    # How many were left out for this person.
    hidden: int
    shown: list[str]
    note: str
    inference: InferenceOut | None
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
            predictions_format=e.predictions_format,
            predictions_size=e.predictions_size,
            key_column=e.key_column,
            prediction_column=e.prediction_column,
            results=view.results,
            hidden=view.hidden,
            shown=e.shown if view.can_edit else [m for m in e.shown if m in view.results],
            note=e.note,
            inference=_inference(e),
            created_by_username=e.created_by_username,
            created_at=e.created_at,
            finished_at=e.finished_at,
            can_edit=view.can_edit,
        )
