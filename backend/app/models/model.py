import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.dataset import MODALITIES, PUBLIC, VISIBILITIES


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _all_in(column: str, values: tuple[str, ...]) -> str:
    """Every item of an array column is one of the values."""
    return f"{column} <@ ARRAY[{', '.join(repr(v) for v in values)}]::varchar[]"


class Model(Base):
    """A model, found at `/models/{owner}/{name}`. What it is made of (the artifacts, the code it points to) is in its
    versions; this describes it and says who may see it.

    The versions and the artifacts themselves are kept by MLflow: a version here points to one of the Model Registry."""

    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint("owner", "name", name="uq_models_owner_name"),
        CheckConstraint(_one_of("visibility", VISIBILITIES), name="visibility"),
        CheckConstraint(_all_in("inputs", MODALITIES), name="inputs"),
        CheckConstraint("downloads >= 0 AND likes_count >= 0", name="counters"),
        CheckConstraint("version >= 0 AND size_bytes >= 0 AND (parameters IS NULL OR parameters >= 0)", name="content"),
        Index("ix_models_updated_at", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The namespace: the name of the person who created it. Never changes.
    owner: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    # What it does and with what data. Chosen when it is created and never changed afterwards (the pre-annotation and
    # the evaluations depend on it): the kinds of annotation task it can do, and the kinds of data it takes.
    tasks: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list, server_default="{}")
    inputs: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list, server_default="{}")
    # What it was built with: `transformers`, `scikit-learn`, `pytorch`...
    library: Mapped[str] = mapped_column(String(50), default="", server_default="")
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    license: Mapped[str] = mapped_column(String(100), default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    visibility: Mapped[str] = mapped_column(String(10), default=PUBLIC, server_default=PUBLIC)
    # The README, in markdown.
    card: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Where the code of the model lives (a GitHub or GitLab repository), as a link for the page. The code that goes with
    # a version is on the version. Validated by the service (https, hosts that are allowed): never fetched from here.
    code_url: Mapped[str | None] = mapped_column(String(512))
    # The number of parameters, when the author says it.
    parameters: Mapped[int | None] = mapped_column(BigInteger)
    # The datasets (`owner/name`) it was trained on: said by the author, not checked against the datasets here.
    trained_on: Mapped[list[str]] = mapped_column(ARRAY(String(201)), default=list, server_default="{}")
    # Counted when it happens, so a list does not count them again for every line.
    downloads: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    likes_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # What the latest version holds, copied here so a list does not look into the versions for every line.
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # The `sub` claim of the identity provider, and the name the author had then (there is no users table).
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    created_by_username: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
