"""follow the reading of the versions

Revision ID: bd9e00d4a771
Revises: aa442bd5e8cc
Create Date: 2026-11-24 15:05:29.096606
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bd9e00d4a771"
down_revision: str | None = "aa442bd5e8cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dataset_versions", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("dataset_versions", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("dataset_versions", "processing_started_at")
    op.drop_column("dataset_versions", "attempts")
