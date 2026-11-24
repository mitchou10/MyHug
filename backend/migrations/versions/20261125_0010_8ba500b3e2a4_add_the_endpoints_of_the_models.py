"""add the endpoints of the models

Revision ID: 8ba500b3e2a4
Revises: 3817ff3cc068
Create Date: 2026-11-25 00:10:11.364567
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8ba500b3e2a4"
down_revision: str | None = "3817ff3cc068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_endpoints",
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("alias", sa.String(length=100), nullable=True),
        sa.Column("input_kind", sa.String(length=20), nullable=False),
        sa.Column("output_kind", sa.String(length=10), nullable=False),
        sa.Column("api", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("auth_header", sa.String(length=100), nullable=True),
        sa.Column("auth_value", sa.String(length=1000), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(kind = 'custom') = (api IS NOT NULL)", name=op.f("ck_model_endpoints_api")),
        sa.CheckConstraint(
            "input_kind IN ('text', 'image', 'audio', 'video', 'tabular', 'timeseries')",
            name=op.f("ck_model_endpoints_input_kind"),
        ),
        sa.CheckConstraint("kind IN ('mlflow', 'custom')", name=op.f("ck_model_endpoints_kind")),
        sa.CheckConstraint(
            "output_kind IN ('labels', 'boxes', 'text', 'values', 'json')", name=op.f("ck_model_endpoints_output_kind")
        ),
        sa.CheckConstraint("(auth_header IS NULL) = (auth_value IS NULL)", name=op.f("ck_model_endpoints_auth")),
        sa.ForeignKeyConstraint(
            ["model_id"], ["models.id"], name=op.f("fk_model_endpoints_model_id_models"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("model_id", name=op.f("pk_model_endpoints")),
    )


def downgrade() -> None:
    op.drop_table("model_endpoints")
