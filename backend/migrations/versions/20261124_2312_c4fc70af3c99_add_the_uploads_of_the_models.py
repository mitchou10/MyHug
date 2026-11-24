"""add the uploads of the models

Revision ID: c4fc70af3c99
Revises: dd4a39dbea7d
Create Date: 2026-11-24 23:12:21.118210
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4fc70af3c99"
down_revision: str | None = "dd4a39dbea7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="open", nullable=False),
        sa.Column("remove", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("code", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'completed', 'aborted', 'expired')", name=op.f("ck_model_uploads_status")
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["models.id"], name=op.f("fk_model_uploads_model_id_models"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["model_versions.id"],
            name=op.f("fk_model_uploads_version_id_model_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_uploads")),
    )
    op.create_index(op.f("ix_model_uploads_created_by"), "model_uploads", ["created_by"], unique=False)
    op.create_index(op.f("ix_model_uploads_model_id"), "model_uploads", ["model_id"], unique=False)
    op.create_index(
        "ix_model_uploads_open_expiry",
        "model_uploads",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "model_upload_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("multipart_id", sa.String(length=512), nullable=True),
        sa.Column("part_size", sa.BigInteger(), nullable=False),
        sa.Column("parts_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "size_bytes > 0 AND part_size >= 0 AND parts_count >= 0", name=op.f("ck_model_upload_files_sizes")
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["model_uploads.id"],
            name=op.f("fk_model_upload_files_upload_id_model_uploads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_upload_files")),
        sa.UniqueConstraint("upload_id", "path", name="uq_model_upload_files_path"),
    )
    op.create_index(op.f("ix_model_upload_files_upload_id"), "model_upload_files", ["upload_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_model_upload_files_upload_id"), table_name="model_upload_files")
    op.drop_table("model_upload_files")
    op.drop_index(
        "ix_model_uploads_open_expiry", table_name="model_uploads", postgresql_where=sa.text("status = 'open'")
    )
    op.drop_index(op.f("ix_model_uploads_model_id"), table_name="model_uploads")
    op.drop_index(op.f("ix_model_uploads_created_by"), table_name="model_uploads")
    op.drop_table("model_uploads")
