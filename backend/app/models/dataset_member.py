import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

READER = "reader"
ANNOTATOR = "annotator"
MAINTAINER = "maintainer"
ROLES = (READER, ANNOTATOR, MAINTAINER)


class DatasetMember(Base):
    """Somebody who has access to a dataset besides its creator, and what they may do with it.

    A public dataset can be read by everybody: the roles matter for a private one, and for editing."""

    __tablename__ = "dataset_members"
    __table_args__ = (
        CheckConstraint(f"role IN ({', '.join(repr(role) for role in ROLES)})", name="role"),
        Index("ix_dataset_members_user_id", "user_id"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    # The `sub` claim of the identity provider.
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    added_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetLike(Base):
    """Somebody likes a dataset. One per person: liking twice changes nothing."""

    __tablename__ = "dataset_likes"
    __table_args__ = (Index("ix_dataset_likes_user_id", "user_id"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
