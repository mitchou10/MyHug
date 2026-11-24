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
from app.models.dataset_upload import ABORTED, COMPLETED, EXPIRED, OPEN, UPLOAD_STATUSES

__all__ = ["ABORTED", "COMPLETED", "EXPIRED", "OPEN", "UPLOAD_STATUSES", "ModelUpload", "ModelUploadFile"]


class ModelUpload(Base):
    """Files on their way to a model. Their content goes straight from the browser to the storage, in parts; this
    follows where it is, so it can be resumed, put together and given up. When it is complete, it makes a version."""

    __tablename__ = "model_uploads"
    __table_args__ = (
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in UPLOAD_STATUSES)})", name="status"),
        # Looking for the ones that went on too long.
        Index("ix_model_uploads_open_expiry", "expires_at", postgresql_where=text("status = 'open'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default=OPEN, server_default=OPEN)
    # The paths to take out of the model in the same version, and what to say about the version.
    remove: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    # The code the version will point to, as announced and already checked (see `code_reference`): None for none.
    code: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    created_by_username: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The version it made, once complete (if the version is deleted, the trace of the upload stays).
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_versions.id", ondelete="SET NULL"))


class ModelUploadFile(Base):
    """One file of an upload: what the browser announced, and where the storage keeps its parts."""

    __tablename__ = "model_upload_files"
    __table_args__ = (
        UniqueConstraint("upload_id", "path", name="uq_model_upload_files_path"),
        CheckConstraint("size_bytes > 0 AND part_size >= 0 AND parts_count >= 0", name="sizes"),
    )

    # Also its name in the storage, and the id of the file it becomes.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_uploads.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(512))
    # The fingerprint the browser announced. It is not believed until a worker has read the file.
    sha256: Mapped[str | None] = mapped_column(String(64))
    # The identifier the storage gave to the upload in parts. None for a file that is already stored in the model:
    # its `storage_key` is the one of the object it is, and nothing is sent.
    multipart_id: Mapped[str | None] = mapped_column(String(512))
    # Every part but the last has this size: the browser cuts the file by it. 0 for a file that is already stored.
    part_size: Mapped[int] = mapped_column(BigInteger)
    parts_count: Mapped[int] = mapped_column(Integer)

    @property
    def already_stored(self) -> bool:
        return self.multipart_id is None
