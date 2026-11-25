"""tell how the predictions were made

Revision ID: 4c6cacc38a75
Revises: 834472c14c98
Create Date: 2026-11-25 11:28:45.782222
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4c6cacc38a75"
down_revision: str | None = "834472c14c98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_evaluations",
        sa.Column("inference", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_model_evaluations_inference_shape"),
        "model_evaluations",
        "inference IS NULL OR jsonb_typeof(inference) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_model_evaluations_inference_shape"), "model_evaluations", type_="check")
    op.drop_column("model_evaluations", "inference")
