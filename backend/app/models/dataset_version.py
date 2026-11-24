import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DatasetVersion(Base):
    """The files of a dataset at a moment. A change of the files makes a new version; the old ones stay readable."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "number", name="uq_dataset_versions_number"),
        CheckConstraint("number >= 1 AND rows >= 0 AND size_bytes >= 0", name="counters"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    # 1, 2, 3...: the order of the versions of one dataset.
    number: Mapped[int] = mapped_column(Integer)
    # How many items: the rows of its data files, or else its images, sounds and videos.
    rows: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
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
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    # Where it is in the dataset: `data/train.parquet`.
    path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(512))
    # Only for the files that hold rows (csv, tsv, jsonl, parquet): their part of the dataset, and how many rows.
    split: Mapped[str | None] = mapped_column(String(20))
    rows: Mapped[int | None] = mapped_column(Integer)
    # Its columns, for the same files: [{"name": "text", "dtype": "string"}].
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
