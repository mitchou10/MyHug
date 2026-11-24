import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# What a dataset holds. A modality never changes: the viewers and the annotation tasks depend on it.
MODALITIES = ("text", "image", "audio", "video", "tabular", "timeseries")
PUBLIC = "public"
PRIVATE = "private"
VISIBILITIES = (PUBLIC, PRIVATE)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Dataset(Base):
    """A dataset, found at `/datasets/{owner}/{name}`. The files and versions come later: this describes it."""

    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("owner", "name", name="uq_datasets_owner_name"),
        CheckConstraint(_one_of("modality", MODALITIES), name="modality"),
        CheckConstraint(_one_of("visibility", VISIBILITIES), name="visibility"),
        CheckConstraint("downloads >= 0 AND likes_count >= 0", name="counters"),
        CheckConstraint("version >= 0 AND rows >= 0 AND size_bytes >= 0", name="content"),
        Index("ix_datasets_updated_at", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The namespace: the name of the person who created it (organizations will come later). Never changes.
    owner: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    modality: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(50), default="", server_default="")
    license: Mapped[str] = mapped_column(String(100), default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    visibility: Mapped[str] = mapped_column(String(10), default=PUBLIC, server_default=PUBLIC)
    # The README, in markdown.
    card: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Counted when it happens, so a list does not count them again for every line.
    downloads: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    likes_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # What the latest version holds, copied here so a list does not look into the versions for every line.
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # The `sub` claim of the identity provider, and the name the author had then (there is no users table).
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    created_by_username: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
