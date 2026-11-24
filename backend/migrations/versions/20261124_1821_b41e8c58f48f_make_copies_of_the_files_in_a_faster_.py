"""make copies of the files in a faster form

Revision ID: b41e8c58f48f
Revises: bd9e00d4a771
Create Date: 2026-11-24 18:21:17.377323
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b41e8c58f48f"
down_revision: str | None = "bd9e00d4a771"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_file_derivatives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_storage_key", sa.String(length=512), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=20), server_default="parquet", nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("multipart_id", sa.String(length=512), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("rows", sa.BigInteger(), nullable=True),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('parquet')", name=op.f("ck_dataset_file_derivatives_kind")),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')", name=op.f("ck_dataset_file_derivatives_status")
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND source_size_bytes >= 0", name=op.f("ck_dataset_file_derivatives_counters")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_file_derivatives")),
        sa.UniqueConstraint("source_storage_key", "kind", "params_hash", name="uq_dataset_file_derivatives_source"),
    )
    op.create_index(
        "ix_dataset_file_derivatives_pending",
        "dataset_file_derivatives",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        op.f("ix_dataset_file_derivatives_source_storage_key"),
        "dataset_file_derivatives",
        ["source_storage_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dataset_file_derivatives_source_storage_key"), table_name="dataset_file_derivatives")
    op.drop_index(
        "ix_dataset_file_derivatives_pending",
        table_name="dataset_file_derivatives",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("dataset_file_derivatives")
