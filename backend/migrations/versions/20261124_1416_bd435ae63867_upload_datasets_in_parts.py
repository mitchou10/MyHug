"""upload datasets in parts

Revision ID: bd435ae63867
Revises: 900414b16281
Create Date: 2026-11-24 14:16:22.161922
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "bd435ae63867"
down_revision: str | None = "900414b16281"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="open", nullable=False),
        sa.Column("remove", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'completed', 'aborted', 'expired')", name=op.f("ck_dataset_uploads_status")
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name=op.f("fk_dataset_uploads_dataset_id_datasets"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_dataset_uploads_version_id_dataset_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_uploads")),
    )
    op.create_index(op.f("ix_dataset_uploads_created_by"), "dataset_uploads", ["created_by"], unique=False)
    op.create_index(op.f("ix_dataset_uploads_dataset_id"), "dataset_uploads", ["dataset_id"], unique=False)
    op.create_index(
        "ix_dataset_uploads_open_expiry",
        "dataset_uploads",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "dataset_upload_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("multipart_id", sa.String(length=512), nullable=False),
        sa.Column("part_size", sa.BigInteger(), nullable=False),
        sa.Column("parts_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "size_bytes > 0 AND part_size > 0 AND parts_count > 0", name=op.f("ck_dataset_upload_files_sizes")
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["dataset_uploads.id"],
            name=op.f("fk_dataset_upload_files_upload_id_dataset_uploads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_upload_files")),
        sa.UniqueConstraint("upload_id", "path", name="uq_dataset_upload_files_path"),
    )
    op.create_index(op.f("ix_dataset_upload_files_upload_id"), "dataset_upload_files", ["upload_id"], unique=False)
    op.alter_column("dataset_files", "sha256", existing_type=sa.VARCHAR(length=64), nullable=True)


def downgrade() -> None:
    # A file that came in parts has no fingerprint yet: it needs one to go back.
    op.execute("UPDATE dataset_files SET sha256 = repeat('0', 64) WHERE sha256 IS NULL")
    op.alter_column("dataset_files", "sha256", existing_type=sa.VARCHAR(length=64), nullable=False)
    op.drop_index(op.f("ix_dataset_upload_files_upload_id"), table_name="dataset_upload_files")
    op.drop_table("dataset_upload_files")
    op.drop_index(
        "ix_dataset_uploads_open_expiry", table_name="dataset_uploads", postgresql_where=sa.text("status = 'open'")
    )
    op.drop_index(op.f("ix_dataset_uploads_dataset_id"), table_name="dataset_uploads")
    op.drop_index(op.f("ix_dataset_uploads_created_by"), table_name="dataset_uploads")
    op.drop_table("dataset_uploads")
