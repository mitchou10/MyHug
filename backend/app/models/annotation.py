import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

OPEN, CLOSED = "open", "closed"
TASK_STATUSES = (OPEN, CLOSED)
# Every kind of task the interface knows (the same list as a model's tasks). The platform implements them one after the
# other: the service refuses the ones that are not there yet.
TASK_TYPES = (
    "classification",
    "ner",
    "qa",
    "regression",
    "row_label",
    "cell_review",
    "column_schema",
    "image_detection",
    "image_segmentation",
    "image_polyline",
    "image_keypoints",
    "image_classification",
    "image_caption",
    "image_vqa",
    "audio_classification",
    "audio_segments",
    "audio_transcription",
    "audio_caption",
    "video_classification",
    "video_segments",
    "video_tracking",
    "video_caption",
    "timeseries_classification",
    "timeseries_segments",
    "timeseries_caption",
)
DRAFT, SUBMITTED = "draft", "submitted"
ANSWER_STATUSES = (DRAFT, SUBMITTED)
HUMAN, MODEL = "human", "model"
SOURCES = (HUMAN, MODEL)


class AnnotationTask(Base):
    """Something to annotate in a dataset: a kind of answer (`type`) for each row of its latest version.

    It points to a dataset and not to a version: it follows the latest one, and an answer keeps the version it was
    given on. What is particular to a kind of task (`text_column`, a scale...) is in `config`, checked by the service
    for each type, so that a new kind of task needs no new column."""

    __tablename__ = "annotation_tasks"
    __table_args__ = (
        CheckConstraint(f"type IN ({', '.join(repr(t) for t in TASK_TYPES)})", name="type"),
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in TASK_STATUSES)})", name="status"),
        CheckConstraint("jsonb_typeof(config) = 'object'", name="config"),
        UniqueConstraint("dataset_id", "name", name="uq_annotation_tasks_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10), default=OPEN, server_default=OPEN)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_by: Mapped[str] = mapped_column(String(255))
    created_by_username: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AnnotationLabel(Base):
    """A choice of a task. Deleting one is **logical**: it stays for the answers that use it, and the interface no
    longer offers it. Renaming or describing it changes the row, never its id: that is what makes a rename free."""

    __tablename__ = "annotation_labels"
    __table_args__ = (
        # The name of a label is free again once the label is deleted.
        Index(
            "uq_annotation_labels_name",
            "task_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("annotation_tasks.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    # The order of the interface, and the keys 1, 2, 3...
    position: Mapped[int] = mapped_column(Integer, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Annotation(Base):
    """The answer of one annotator to one row of a task: at most one of each. It points to the **exact version** of the
    dataset and to a hash of the text it was given on, so that an answer to a text that changed since can be told."""

    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in ANSWER_STATUSES)})", name="status"),
        CheckConstraint(f"source IN ({', '.join(repr(s) for s in SOURCES)})", name="source"),
        CheckConstraint("row_index >= 0", name="row_index"),
        UniqueConstraint("task_id", "split", "row_index", "annotator", name="uq_annotations_row"),
        Index("ix_annotations_task_id_annotator", "task_id", "annotator"),
        Index("ix_annotations_task_id_split_row_index", "task_id", "split", "row_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("annotation_tasks.id", ondelete="CASCADE"))
    split: Mapped[str] = mapped_column(String(50))
    row_index: Mapped[int] = mapped_column(Integer)
    # The version of the dataset the answer was given on (its number), and the fingerprint of the text it saw.
    version_number: Mapped[int] = mapped_column(Integer)
    text_sha256: Mapped[str] = mapped_column(String(64))
    annotator: Mapped[str] = mapped_column(String(255))
    annotator_username: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10), default=SUBMITTED, server_default=SUBMITTED)
    # Who made the answer: a person (`human`), or it came from a proposal of a model (later).
    source: Mapped[str] = mapped_column(String(10), default=HUMAN, server_default=HUMAN)
    # Classification: the label chosen, and why (free, optional).
    label_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("annotation_labels.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
