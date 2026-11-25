import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

READ, WRITE = "read", "write"
SCOPES = (READ, WRITE)


class AccessToken(Base):
    """A key that lets a program act as a person (a script, a notebook, the SDK), with their rights, never more.

    The token itself is shown once, when it is made: only its SHA-256 is kept (it is long and random, so a slow hash is
    not needed), and the first characters of it, to recognise it in a list."""

    __tablename__ = "access_tokens"
    __table_args__ = (
        CheckConstraint(f"scope IN ({', '.join(repr(s) for s in SCOPES)})", name="scope"),
        Index("ix_access_tokens_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Whose it is: the `sub` claim of the identity provider, and what is needed to act as them without asking the
    # provider again (a program has no session).
    user_id: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    email: Mapped[str] = mapped_column(String(255), default="", server_default="")
    name: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(5))
    # What a person can read of it afterwards: `mh_AbCdEfGh`.
    prefix: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["READ", "SCOPES", "WRITE", "AccessToken"]
