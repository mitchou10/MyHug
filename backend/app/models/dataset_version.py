import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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

# What a version is going through. It is created `pending`: a worker reads its files to count the rows and find the
# columns and the parts, then it is `ready`. The API never reads the content of a file to answer a request that writes.
PENDING, PROCESSING, READY, FAILED = "pending", "processing", "ready", "failed"
STATUSES = (PENDING, PROCESSING, READY, FAILED)


class DatasetVersion(Base):
    """The files of a dataset at a moment. A change of the files makes a new version; the old ones stay readable."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "number", name="uq_dataset_versions_number"),
        CheckConstraint("number >= 1 AND rows >= 0 AND size_bytes >= 0", name="counters"),
        CheckConstraint(f"status IN ({', '.join(repr(status) for status in STATUSES)})", name="status"),
        # The worker takes the oldest pending versions first.
        Index("ix_dataset_versions_pending", "created_at", postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    # 1, 2, 3...: the order of the versions of one dataset.
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default=PENDING, server_default=PENDING)
    # Why it failed, when it did: the file that could not be read.
    error: Mapped[str | None] = mapped_column(Text)
    # How many items: the rows of its data files, or else its images, sounds and videos. Not known until it is ready.
    rows: Mapped[int | None] = mapped_column(BigInteger)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # What the preview shows as columns: [{"name": "text", "dtype": "string"}], read from the first data file.
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[str] = mapped_column(String(255))
    created_by_username: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetFile(Base):
    """A file of a version. Its content is in the storage under a key made of its fingerprint, so a file that did not
    change from one version to the next is stored once."""

    __tablename__ = "dataset_files"
    __table_args__ = (
        UniqueConstraint("version_id", "path", name="uq_dataset_files_path"),
        CheckConstraint("size_bytes >= 0", name="size"),
        # Looking for a file that has the same content as one that is announced.
        Index("ix_dataset_files_sha256", "sha256", postgresql_where=text("sha256 IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    # Where it is in the dataset: `data/train.parquet`.
    path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Its fingerprint. A file that came in parts does not have one until a worker has read it.
    sha256: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(512))
    # Only for the files that hold rows (csv, tsv, jsonl, parquet): their part of the dataset, and how many rows.
    split: Mapped[str | None] = mapped_column(String(20))
    rows: Mapped[int | None] = mapped_column(Integer)
    # Its columns, for the same files: [{"name": "text", "dtype": "string"}].
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
