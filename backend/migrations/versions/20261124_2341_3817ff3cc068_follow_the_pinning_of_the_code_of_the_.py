"""follow the pinning of the code of the versions

Revision ID: 3817ff3cc068
Revises: c4fc70af3c99
Create Date: 2026-11-24 23:41:55.839367
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3817ff3cc068"
down_revision: str | None = "c4fc70af3c99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("code_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("model_versions", sa.Column("code_started_at", sa.DateTime(timezone=True), nullable=True))
    # The rule on the counters is written by hand (the autogeneration does not see a change of a check): it now holds
    # for the new one too.
    op.drop_constraint(op.f("ck_model_versions_counters"), "model_versions", type_="check")
    op.create_check_constraint(
        op.f("ck_model_versions_counters"),
        "model_versions",
        "number >= 1 AND size_bytes >= 0 AND attempts >= 0 AND code_attempts >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_model_versions_counters"), "model_versions", type_="check")
    op.create_check_constraint(
        op.f("ck_model_versions_counters"), "model_versions", "number >= 1 AND size_bytes >= 0 AND attempts >= 0"
    )
    op.drop_column("model_versions", "code_started_at")
    op.drop_column("model_versions", "code_attempts")
