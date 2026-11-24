"""create dataset versions and files

Revision ID: e99afcac1778
Revises: d8193a9e5e81
Create Date: 2026-11-24 13:37:37.258724
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e99afcac1778"
down_revision: str | None = "d8193a9e5e81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("rows", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("number >= 1 AND rows >= 0 AND size_bytes >= 0", name=op.f("ck_dataset_versions_counters")),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name=op.f("fk_dataset_versions_dataset_id_datasets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_versions")),
        sa.UniqueConstraint("dataset_id", "number", name="uq_dataset_versions_number"),
    )
    op.create_index(op.f("ix_dataset_versions_dataset_id"), "dataset_versions", ["dataset_id"], unique=False)
    op.create_table(
        "dataset_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("split", sa.String(length=20), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_dataset_files_size")),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_dataset_files_version_id_dataset_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_files")),
        sa.UniqueConstraint("version_id", "path", name="uq_dataset_files_path"),
    )
    op.create_index(op.f("ix_dataset_files_version_id"), "dataset_files", ["version_id"], unique=False)
    op.add_column("datasets", sa.Column("version", sa.Integer(), server_default="0", nullable=False))
    op.add_column("datasets", sa.Column("rows", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("datasets", sa.Column("size_bytes", sa.BigInteger(), server_default="0", nullable=False))
    # Alembic does not see a check constraint added to a table that exists.
    op.create_check_constraint(
        op.f("ck_datasets_content"), "datasets", "version >= 0 AND rows >= 0 AND size_bytes >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_datasets_content"), "datasets", type_="check")
    op.drop_column("datasets", "size_bytes")
    op.drop_column("datasets", "rows")
    op.drop_column("datasets", "version")
    op.drop_index(op.f("ix_dataset_files_version_id"), table_name="dataset_files")
    op.drop_table("dataset_files")
    op.drop_index(op.f("ix_dataset_versions_dataset_id"), table_name="dataset_versions")
    op.drop_table("dataset_versions")
