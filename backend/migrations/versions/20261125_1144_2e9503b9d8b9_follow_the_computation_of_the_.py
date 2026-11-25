"""follow the computation of the evaluations

Revision ID: 2e9503b9d8b9
Revises: 4c6cacc38a75
Create Date: 2026-11-25 11:44:08.306486
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2e9503b9d8b9"
down_revision: str | None = "4c6cacc38a75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_evaluations", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("model_evaluations", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f("ck_model_evaluations_attempts"), "model_evaluations", "attempts >= 0")
    op.create_index(
        "ix_model_evaluations_waiting",
        "model_evaluations",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_evaluations_waiting",
        table_name="model_evaluations",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.drop_constraint(op.f("ck_model_evaluations_attempts"), "model_evaluations", type_="check")
    op.drop_column("model_evaluations", "processing_started_at")
    op.drop_column("model_evaluations", "attempts")
