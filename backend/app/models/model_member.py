import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

READER = "reader"
MAINTAINER = "maintainer"
# What a member can be. The owner (the creator) and the admins of the platform are not members: they are worked out.
ROLES = (READER, MAINTAINER)


class ModelMember(Base):
    """Somebody who has access to a model besides its creator, and what they may do with it.

    A public model can be read by everybody: the roles matter for a private one, and for editing."""

    __tablename__ = "model_members"
    __table_args__ = (
        CheckConstraint(f"role IN ({', '.join(repr(role) for role in ROLES)})", name="role"),
        Index("ix_model_members_user_id", "user_id"),
    )

    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), primary_key=True)
    # The `sub` claim of the identity provider.
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    added_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelLike(Base):
    """Somebody likes a model. One per person: liking twice changes nothing."""

    __tablename__ = "model_likes"
    __table_args__ = (Index("ix_model_likes_user_id", "user_id"),)

    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
