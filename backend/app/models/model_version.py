import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# What a version is going through. It is created `pending`: a worker checks what it needs to (its files' fingerprints),
# then it is `ready`.
PENDING, PROCESSING, READY, FAILED = "pending", "processing", "ready", "failed"
STATUSES = (PENDING, PROCESSING, READY, FAILED)

# What the code a version points to is going through. `none`: there is none. A branch or a tag moves, so the worker
# finds the commit it is on (`pinned`). `unverified`: it could not be (private, or not found): the link is kept as
# written.
NONE, UNRESOLVED, RESOLVING, PINNED, UNVERIFIED, CODE_FAILED = (
    "none",
    "unresolved",
    "resolving",
    "pinned",
    "unverified",
    "failed",
)
CODE_STATES = (NONE, UNRESOLVED, RESOLVING, PINNED, UNVERIFIED, CODE_FAILED)
# What the author wrote as the reference of the code.
COMMIT, TAG, BRANCH, UNKNOWN = "commit", "tag", "branch", "unknown"
CODE_REF_KINDS = (COMMIT, TAG, BRANCH, UNKNOWN)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ModelVersion(Base):
    """The weights and the code of a model at a moment. A change makes a new version; the old ones stay readable.

    A version is **an artifact, a code reference, or both**: the weights alone may be enough (a standard architecture,
    or a model packaged for MLflow); otherwise it points to the code that runs them. The artifacts are in MLflow (the
    reference below) and their files are listed in `model_files`; the code is only a link, never cloned or run here.
    That a version has at least one of the two is checked by the service that creates it: the files are in another
    table."""

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("model_id", "number", name="uq_model_versions_number"),
        CheckConstraint("number >= 1 AND size_bytes >= 0 AND attempts >= 0 AND code_attempts >= 0", name="counters"),
        CheckConstraint(_one_of("status", STATUSES), name="status"),
        CheckConstraint(_one_of("code_state", CODE_STATES), name="code_state"),
        CheckConstraint(_one_of("code_ref_kind", CODE_REF_KINDS), name="code_ref_kind"),
        # Both parts of the reference to MLflow, or neither (a version that is only code has none).
        CheckConstraint("(mlflow_name IS NULL) = (mlflow_version IS NULL)", name="mlflow"),
        # A commit is 40 characters (SHA-1) or 64 (SHA-256) of hexadecimal.
        CheckConstraint("code_sha IS NULL OR code_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name="code_sha"),
        # There is code to follow exactly when there is a link to it.
        CheckConstraint(
            "(code_state = 'none' AND code_url IS NULL) OR (code_state <> 'none' AND code_url IS NOT NULL)",
            name="code_link",
        ),
        # The commit is known exactly when the code is pinned: never before, and never missing once it is.
        CheckConstraint("(code_state = 'pinned') = (code_sha IS NOT NULL)", name="code_pinned"),
        # A version of MLflow belongs to one version here.
        Index(
            "uq_model_versions_mlflow",
            "mlflow_name",
            "mlflow_version",
            unique=True,
            postgresql_where=text("mlflow_name IS NOT NULL"),
        ),
        # The worker takes the oldest pending versions first, and looks for the code that is still to be pinned.
        Index("ix_model_versions_pending", "created_at", postgresql_where=text("status = 'pending'")),
        Index("ix_model_versions_code_unresolved", "created_at", postgresql_where=text("code_state = 'unresolved'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), index=True)
    # 1, 2, 3...: the order of the versions of one model.
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default=PENDING, server_default=PENDING)
    # Why it failed, when it did.
    error: Mapped[str | None] = mapped_column(Text)
    # How many times a worker took it in hand, and since when it is checked: a dead worker leaves it `processing`.
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # The version of the Model Registry of MLflow it is. None for a version that is only code.
    mlflow_name: Mapped[str | None] = mapped_column(String(255))
    mlflow_version: Mapped[str | None] = mapped_column(String(50))
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64))
    # Whether MLflow can serve it (it has a flavor). A model that is only files is stored and downloaded, not served.
    servable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # ---- the code it points to: a GitHub or GitLab repository, validated by the service, pinned by the worker
    code_url: Mapped[str | None] = mapped_column(String(512))
    # What the author wrote: a commit, a tag or a branch. It is not changed when the worker pins it.
    code_ref: Mapped[str | None] = mapped_column(String(255))
    code_ref_kind: Mapped[str] = mapped_column(String(10), default=UNKNOWN, server_default=UNKNOWN)
    # A sub-folder of the repository, and the file that runs the model (`src/predict.py`).
    code_path: Mapped[str | None] = mapped_column(String(512))
    entrypoint: Mapped[str | None] = mapped_column(String(512))
    # The commit it was resolved to. Null until then, and never changed afterwards: a version is a snapshot.
    code_sha: Mapped[str | None] = mapped_column(String(64))
    code_state: Mapped[str] = mapped_column(String(12), default=NONE, server_default=NONE)
    code_error: Mapped[str | None] = mapped_column(Text)
    # How many times a worker took the code in hand, and since when it is resolved (a dead worker leaves it
    # `resolving`).
    # Apart from `attempts` and `processing_started_at`: the check of the files and this are two jobs of their own.
    code_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    code_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_by_username: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelFile(Base):
    """A file of a version. Its content is in the storage under a key made of its fingerprint, so a file that did not
    change from one version to the next is stored once."""

    __tablename__ = "model_files"
    __table_args__ = (
        UniqueConstraint("version_id", "path", name="uq_model_files_path"),
        CheckConstraint("size_bytes >= 0", name="size"),
        # Looking for a file that has the same content as one that is announced.
        Index("ix_model_files_sha256", "sha256", postgresql_where=text("sha256 IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), index=True)
    # Where it is in the model: `weights/model.safetensors`.
    path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Its fingerprint. A file that came in parts does not have one until a worker has read it.
    sha256: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
