"""add the tables of the models

Revision ID: dd4a39dbea7d
Revises: b41e8c58f48f
Create Date: 2026-11-24 19:36:47.682605
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dd4a39dbea7d"
down_revision: str | None = "b41e8c58f48f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("tasks", postgresql.ARRAY(sa.String(length=40)), server_default="{}", nullable=False),
        sa.Column("inputs", postgresql.ARRAY(sa.String(length=20)), server_default="{}", nullable=False),
        sa.Column("library", sa.String(length=50), server_default="", nullable=False),
        sa.Column("languages", postgresql.ARRAY(sa.String(length=50)), server_default="{}", nullable=False),
        sa.Column("license", sa.String(length=100), server_default="", nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String(length=50)), server_default="{}", nullable=False),
        sa.Column("visibility", sa.String(length=10), server_default="public", nullable=False),
        sa.Column("card", sa.Text(), server_default="", nullable=False),
        sa.Column("code_url", sa.String(length=512), nullable=True),
        sa.Column("parameters", sa.BigInteger(), nullable=True),
        sa.Column("trained_on", postgresql.ARRAY(sa.String(length=201)), server_default="{}", nullable=False),
        sa.Column("downloads", sa.Integer(), server_default="0", nullable=False),
        sa.Column("likes_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "inputs <@ ARRAY['text', 'image', 'audio', 'video', 'tabular', 'timeseries']::varchar[]",
            name=op.f("ck_models_inputs"),
        ),
        sa.CheckConstraint("visibility IN ('public', 'private')", name=op.f("ck_models_visibility")),
        sa.CheckConstraint("downloads >= 0 AND likes_count >= 0", name=op.f("ck_models_counters")),
        sa.CheckConstraint(
            "version >= 0 AND size_bytes >= 0 AND (parameters IS NULL OR parameters >= 0)",
            name=op.f("ck_models_content"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_models")),
        sa.UniqueConstraint("owner", "name", name="uq_models_owner_name"),
    )
    op.create_index(op.f("ix_models_created_by"), "models", ["created_by"], unique=False)
    op.create_index("ix_models_updated_at", "models", ["updated_at"], unique=False)
    op.create_table(
        "model_likes",
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_id"], ["models.id"], name=op.f("fk_model_likes_model_id_models"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("model_id", "user_id", name=op.f("pk_model_likes")),
    )
    op.create_index("ix_model_likes_user_id", "model_likes", ["user_id"], unique=False)
    op.create_table(
        "model_members",
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("added_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('reader', 'maintainer')", name=op.f("ck_model_members_role")),
        sa.ForeignKeyConstraint(
            ["model_id"], ["models.id"], name=op.f("fk_model_members_model_id_models"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("model_id", "user_id", name=op.f("pk_model_members")),
    )
    op.create_index("ix_model_members_user_id", "model_members", ["user_id"], unique=False)
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("mlflow_name", sa.String(length=255), nullable=True),
        sa.Column("mlflow_version", sa.String(length=50), nullable=True),
        sa.Column("mlflow_run_id", sa.String(length=64), nullable=True),
        sa.Column("servable", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("code_url", sa.String(length=512), nullable=True),
        sa.Column("code_ref", sa.String(length=255), nullable=True),
        sa.Column("code_ref_kind", sa.String(length=10), server_default="unknown", nullable=False),
        sa.Column("code_path", sa.String(length=512), nullable=True),
        sa.Column("entrypoint", sa.String(length=512), nullable=True),
        sa.Column("code_sha", sa.String(length=64), nullable=True),
        sa.Column("code_state", sa.String(length=12), server_default="none", nullable=False),
        sa.Column("code_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(code_state = 'none' AND code_url IS NULL) OR (code_state <> 'none' AND code_url IS NOT NULL)",
            name=op.f("ck_model_versions_code_link"),
        ),
        sa.CheckConstraint(
            "(code_state = 'pinned') = (code_sha IS NOT NULL)", name=op.f("ck_model_versions_code_pinned")
        ),
        sa.CheckConstraint(
            "code_ref_kind IN ('commit', 'tag', 'branch', 'unknown')", name=op.f("ck_model_versions_code_ref_kind")
        ),
        sa.CheckConstraint(
            "code_sha IS NULL OR code_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name=op.f("ck_model_versions_code_sha")
        ),
        sa.CheckConstraint(
            "code_state IN ('none', 'unresolved', 'resolving', 'pinned', 'unverified', 'failed')",
            name=op.f("ck_model_versions_code_state"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')", name=op.f("ck_model_versions_status")
        ),
        sa.CheckConstraint("(mlflow_name IS NULL) = (mlflow_version IS NULL)", name=op.f("ck_model_versions_mlflow")),
        sa.CheckConstraint(
            "number >= 1 AND size_bytes >= 0 AND attempts >= 0", name=op.f("ck_model_versions_counters")
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["models.id"], name=op.f("fk_model_versions_model_id_models"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint("model_id", "number", name="uq_model_versions_number"),
    )
    op.create_index(
        "ix_model_versions_code_unresolved",
        "model_versions",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("code_state = 'unresolved'"),
    )
    op.create_index(op.f("ix_model_versions_model_id"), "model_versions", ["model_id"], unique=False)
    op.create_index(
        "ix_model_versions_pending",
        "model_versions",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_model_versions_mlflow",
        "model_versions",
        ["mlflow_name", "mlflow_version"],
        unique=True,
        postgresql_where=sa.text("mlflow_name IS NOT NULL"),
    )
    op.create_table(
        "model_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_model_files_size")),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["model_versions.id"],
            name=op.f("fk_model_files_version_id_model_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_files")),
        sa.UniqueConstraint("version_id", "path", name="uq_model_files_path"),
    )
    op.create_index(
        "ix_model_files_sha256", "model_files", ["sha256"], unique=False, postgresql_where=sa.text("sha256 IS NOT NULL")
    )
    op.create_index(op.f("ix_model_files_version_id"), "model_files", ["version_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_model_files_version_id"), table_name="model_files")
    op.drop_index("ix_model_files_sha256", table_name="model_files", postgresql_where=sa.text("sha256 IS NOT NULL"))
    op.drop_table("model_files")
    op.drop_index(
        "uq_model_versions_mlflow", table_name="model_versions", postgresql_where=sa.text("mlflow_name IS NOT NULL")
    )
    op.drop_index(
        "ix_model_versions_pending", table_name="model_versions", postgresql_where=sa.text("status = 'pending'")
    )
    op.drop_index(op.f("ix_model_versions_model_id"), table_name="model_versions")
    op.drop_index(
        "ix_model_versions_code_unresolved",
        table_name="model_versions",
        postgresql_where=sa.text("code_state = 'unresolved'"),
    )
    op.drop_table("model_versions")
    op.drop_index("ix_model_members_user_id", table_name="model_members")
    op.drop_table("model_members")
    op.drop_index("ix_model_likes_user_id", table_name="model_likes")
    op.drop_table("model_likes")
    op.drop_index("ix_models_updated_at", table_name="models")
    op.drop_index(op.f("ix_models_created_by"), table_name="models")
    op.drop_table("models")
