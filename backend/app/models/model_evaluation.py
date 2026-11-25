import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

MEASURED, SUBMITTED = "measured", "submitted"
SOURCES = (MEASURED, SUBMITTED)
PENDING, RUNNING, DONE, FAILED, STOPPED = "pending", "running", "done", "failed", "stopped"
STATUSES = (PENDING, RUNNING, DONE, FAILED, STOPPED)


class ModelEvaluation(Base):
    """How a version of a model performs on a part of a dataset, for one of its tasks.

    It holds **every** metric of the task; `shown` is the ones its author chose to show to the others. Its `source` says
    where the numbers come from: the platform measured them, or a person sent them (and it is always shown as such).
    It goes with its version and its model; it stays when the dataset is deleted (the address is kept)."""

    __tablename__ = "model_evaluations"
    __table_args__ = (
        CheckConstraint(f"source IN ({', '.join(repr(s) for s in SOURCES)})", name="source"),
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in STATUSES)})", name="status"),
        # A result somebody sent is a finished one: there is nothing to follow.
        CheckConstraint("source <> 'submitted' OR status = 'done'", name="submitted_is_done"),
        CheckConstraint("jsonb_typeof(results) = 'object' AND jsonb_typeof(shown) = 'array'", name="json_shapes"),
        CheckConstraint("status <> 'done' OR results <> '{}'::jsonb", name="done_has_results"),
        CheckConstraint("items IS NULL OR items >= 0", name="items"),
        Index("ix_model_evaluations_model_id_created_at", "model_id", "created_at"),
        Index("ix_model_evaluations_version_id", "version_id"),
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
    source: Mapped[str] = mapped_column(String(10))
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
