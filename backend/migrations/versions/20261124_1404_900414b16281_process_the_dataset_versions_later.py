"""process the dataset versions later

Revision ID: 900414b16281
Revises: e99afcac1778
Create Date: 2026-11-24 14:04:02.609348
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "900414b16281"
down_revision: str | None = "e99afcac1778"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The versions that exist were read when they were sent: they are ready. The next ones start pending.
    op.add_column("dataset_versions", sa.Column("status", sa.String(length=12), server_default="ready", nullable=False))
    op.alter_column("dataset_versions", "status", server_default="pending")
    op.create_check_constraint(
        op.f("ck_dataset_versions_status"), "dataset_versions", "status IN ('pending', 'processing', 'ready', 'failed')"
    )
    op.add_column("dataset_versions", sa.Column("error", sa.Text(), nullable=True))
    # The number of rows is not known until a worker has read the files.
    op.alter_column("dataset_versions", "rows", existing_type=sa.BigInteger(), nullable=True, server_default=None)
    op.alter_column("datasets", "rows", existing_type=sa.BigInteger(), nullable=True, server_default=None)
    op.create_index(
        "ix_dataset_versions_pending",
        "dataset_versions",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dataset_versions_pending", table_name="dataset_versions", postgresql_where=sa.text("status = 'pending'")
    )
    op.execute("UPDATE datasets SET rows = 0 WHERE rows IS NULL")
    op.execute("UPDATE dataset_versions SET rows = 0 WHERE rows IS NULL")
    op.alter_column("datasets", "rows", existing_type=sa.BigInteger(), nullable=False, server_default="0")
    op.alter_column("dataset_versions", "rows", existing_type=sa.BigInteger(), nullable=False, server_default="0")
    op.drop_column("dataset_versions", "error")
    op.drop_constraint(op.f("ck_dataset_versions_status"), "dataset_versions", type_="check")
    op.drop_column("dataset_versions", "status")
