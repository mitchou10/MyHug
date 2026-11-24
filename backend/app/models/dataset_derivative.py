import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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

PARQUET = "parquet"
KINDS = (PARQUET,)
# What a copy is going through: created `pending`, read by a worker (`processing`), then `ready`, or `failed`.
PENDING, PROCESSING, READY, FAILED = "pending", "processing", "ready", "failed"
STATUSES = (PENDING, PROCESSING, READY, FAILED)
# Bumped when the way a file is converted changes: the copies made the old way are not the ones looked for any more.
CONVERTER = "parquet-1"


class DatasetFileDerivative(Base):
    """A copy of a file of a dataset in a form that is faster to read, made by the system. It is not a file of the
    dataset: it is not listed, not counted in the rows or the size, and the original is never replaced.

    It belongs to the content of the source file (its storage key), not to a version: every version that keeps the
    file shares it, and it is never made twice."""

    __tablename__ = "dataset_file_derivatives"
    __table_args__ = (
        UniqueConstraint("source_storage_key", "kind", "params_hash", name="uq_dataset_file_derivatives_source"),
        CheckConstraint("attempts >= 0 AND source_size_bytes >= 0", name="counters"),
        CheckConstraint(f"status IN ({', '.join(repr(status) for status in STATUSES)})", name="status"),
        CheckConstraint(f"kind IN ({', '.join(repr(kind) for kind in KINDS)})", name="kind"),
        # The sweep looks for the copies nobody is making.
        Index("ix_dataset_file_derivatives_pending", "created_at", postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_storage_key: Mapped[str] = mapped_column(String(512), index=True)
    # A path the source has in the dataset: the worker reads its name to know the format (csv, tsv, jsonl).
    source_path: Mapped[str] = mapped_column(String(512))
    source_size_bytes: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20), default=PARQUET, server_default=PARQUET)
    # What the copy was made with (see CONVERTER): a copy made another way is another copy.
    params_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default=PENDING, server_default=PENDING)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The copy goes to the storage in parts, like a large upload: its identifier while it is being written.
    multipart_id: Mapped[str | None] = mapped_column(String(512))
    # Where the copy is, and what it is, once `ready`.
    storage_key: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    rows: Mapped[int | None] = mapped_column(BigInteger)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
