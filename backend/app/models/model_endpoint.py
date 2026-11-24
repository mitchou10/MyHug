import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.dataset import MODALITIES

# Where the predictions come from: an MLflow model server (it answers `/ping` and `/invocations`), or a service of
# somebody's own whose API the editor describes.
MLFLOW, CUSTOM = "mlflow", "custom"
KINDS = (MLFLOW, CUSTOM)
# What comes out: labels (text -> classes), boxes (image -> detections), text, values (numbers), or anything else
# (json).
OUTPUTS = ("labels", "boxes", "text", "values", "json")


class ModelEndpoint(Base):
    """Where a model can be tried: the address of a server that serves it. The platform does not run models, it only
    forwards a request there (see the relay), and **only when an endpoint is set**: a model without one is stored and
    downloaded, never served.

    The address and the secret are for the editors of the model: nothing here is ever in an answer to a reader."""

    __tablename__ = "model_endpoints"
    __table_args__ = (
        CheckConstraint(f"kind IN ({', '.join(repr(k) for k in KINDS)})", name="kind"),
        CheckConstraint(f"input_kind IN ({', '.join(repr(k) for k in MODALITIES)})", name="input_kind"),
        CheckConstraint(f"output_kind IN ({', '.join(repr(k) for k in OUTPUTS)})", name="output_kind"),
        # The description of the API is for the other kind only: an MLflow server has the same API everywhere.
        CheckConstraint("(kind = 'custom') = (api IS NOT NULL)", name="api"),
        CheckConstraint("(auth_header IS NULL) = (auth_value IS NULL)", name="auth"),
    )

    # One per model.
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    # Checked against the allowlist of the platform when it is set and every time it is called.
    url: Mapped[str] = mapped_column(String(512))
    # The alias or the version it serves in the registry (`production`): for the page, nothing is looked up with it.
    alias: Mapped[str | None] = mapped_column(String(100))
    input_kind: Mapped[str] = mapped_column(String(20))
    output_kind: Mapped[str] = mapped_column(String(10))
    # Custom only (no API is NULL, not a JSON `null`):
    # {"path": "/predict", "input_field": "text", "output_path": "predictions.0.label"}.
    api: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # A header the service wants (`Authorization`, `X-Api-Key`) and its value. Written, never read back: no answer of
    # the API holds it. It is kept as it was sent (there is no key to encrypt it with here): whoever reads the
    # database reads it.
    auth_header: Mapped[str | None] = mapped_column(String(100))
    auth_value: Mapped[str | None] = mapped_column(String(1000))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = ["CUSTOM", "KINDS", "MLFLOW", "OUTPUTS", "ModelEndpoint"]
