import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Where the predictions come from. The platform computes the metrics, always, and no number a person sends is ever
# published: `predictions` (a person sent them), `endpoint` (the platform called the model that is served somewhere),
# `inference` (the platform ran the model itself).
PREDICTIONS, ENDPOINT, INFERENCE = "predictions", "endpoint", "inference"
SOURCES = (PREDICTIONS, ENDPOINT, INFERENCE)
# `uploading`: the file of predictions is still going to the storage. Then `pending` (a worker has to compute),
# `running`, and `done` or `failed` (or `stopped` by the person).
UPLOADING, PENDING, RUNNING, DONE, FAILED, STOPPED = "uploading", "pending", "running", "done", "failed", "stopped"
STATUSES = (UPLOADING, PENDING, RUNNING, DONE, FAILED, STOPPED)
FORMATS = ("jsonl", "csv", "parquet")


class ModelEvaluation(Base):
    """How a version of a model performs on a part of a dataset, for one of its tasks.

    It holds **every** metric of the task; `shown` is the ones its author chose to show to the others. The platform
    computes the metrics, always, from predictions (see `source`): no value a person sends is published.
    It goes with its version and its model; it stays when the dataset is deleted (the address is kept)."""

    __tablename__ = "model_evaluations"
    __table_args__ = (
        CheckConstraint(f"source IN ({', '.join(repr(s) for s in SOURCES)})", name="source"),
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in STATUSES)})", name="status"),
        CheckConstraint(
            f"predictions_format IS NULL OR predictions_format IN ({', '.join(repr(f) for f in FORMATS)})",
            name="format",
        ),
        # A file that is still going to the storage has its upload and its time limit.
        CheckConstraint(
            "status <> 'uploading' OR (multipart_id IS NOT NULL AND expires_at IS NOT NULL)",
            name="uploading_has_upload",
        ),
        CheckConstraint("jsonb_typeof(results) = 'object' AND jsonb_typeof(shown) = 'array'", name="json_shapes"),
        CheckConstraint("status <> 'done' OR results <> '{}'::jsonb", name="done_has_results"),
        CheckConstraint("items IS NULL OR items >= 0", name="items"),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("inference IS NULL OR jsonb_typeof(inference) = 'object'", name="inference_shape"),
        Index("ix_model_evaluations_model_id_created_at", "model_id", "created_at"),
        Index("ix_model_evaluations_version_id", "version_id"),
        # The sweep looks for the ones nobody is computing.
        Index("ix_model_evaluations_waiting", "created_at", postgresql_where=text("status IN ('pending', 'running')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"))
    # The number of the version, as people say it (`v2`): kept so that a list needs no join.
    version_number: Mapped[int] = mapped_column(Integer)
    task: Mapped[str] = mapped_column(String(40))
    # What it was evaluated on: the dataset by its address (kept if the dataset goes), its version, the split, and the
    # columns that were read. Any of them may be unknown for a result somebody sent.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"))
    dataset_address: Mapped[str | None] = mapped_column(String(201))
    dataset_version: Mapped[int | None] = mapped_column(Integer)
    split: Mapped[str | None] = mapped_column(String(50))
    input_column: Mapped[str | None] = mapped_column(String(255))
    target_column: Mapped[str | None] = mapped_column(String(255))
    items: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(12))
    # The predictions a person sent: one file (`jsonl`, `csv` or `parquet`) that goes to the storage in parts, with
    # one row for each item of the split: `key_column` says which column of the file says which item it is (empty:
    # the position of the line, from 0, is the position of the item), `prediction_column` where the prediction is.
    predictions_key: Mapped[str | None] = mapped_column(String(512))
    predictions_format: Mapped[str | None] = mapped_column(String(10))
    predictions_size: Mapped[int | None] = mapped_column(BigInteger)
    key_column: Mapped[str | None] = mapped_column(String(255))
    prediction_column: Mapped[str] = mapped_column(String(255), default="prediction", server_default="prediction")
    # While it goes to the storage: its identifier, the size of its parts, and the time it has.
    multipart_id: Mapped[str | None] = mapped_column(String(512))
    part_size: Mapped[int | None] = mapped_column(Integer)
    parts_count: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How the predictions were made: the time it took, and the hardware (`schemas/evaluation.py` says its shape). For
    # predictions a person sent it is what they say; for a model the platform ran, it is what the platform measured.
    inference: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # The worker that computes the metrics takes the evaluation in hand for itself alone (like a version it reads).
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default=PENDING, server_default=PENDING)
    error: Mapped[str | None] = mapped_column(Text)
    # {metric id: value}, and the ids of the ones shown to people who cannot edit the model.
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    shown: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # How a result somebody sent was obtained (their words).
    note: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    created_by: Mapped[str] = mapped_column(String(255))
    created_by_username: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
