"""create datasets

Revision ID: d8193a9e5e81
Revises: c83b3b37ca24
Create Date: 2026-11-24 13:29:54.964437
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8193a9e5e81"
down_revision: str | None = "c83b3b37ca24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("modality", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=50), server_default="", nullable=False),
        sa.Column("license", sa.String(length=100), server_default="", nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String(length=50)), server_default="{}", nullable=False),
        sa.Column("visibility", sa.String(length=10), server_default="public", nullable=False),
        sa.Column("card", sa.Text(), server_default="", nullable=False),
        sa.Column("downloads", sa.Integer(), server_default="0", nullable=False),
        sa.Column("likes_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "modality IN ('text', 'image', 'audio', 'video', 'tabular', 'timeseries')",
            name=op.f("ck_datasets_modality"),
        ),
        sa.CheckConstraint("visibility IN ('public', 'private')", name=op.f("ck_datasets_visibility")),
        sa.CheckConstraint("downloads >= 0 AND likes_count >= 0", name=op.f("ck_datasets_counters")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
        sa.UniqueConstraint("owner", "name", name="uq_datasets_owner_name"),
    )
    op.create_index(op.f("ix_datasets_created_by"), "datasets", ["created_by"], unique=False)
    op.create_index("ix_datasets_updated_at", "datasets", ["updated_at"], unique=False)
    op.create_table(
        "dataset_likes",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name=op.f("fk_dataset_likes_dataset_id_datasets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("dataset_id", "user_id", name=op.f("pk_dataset_likes")),
    )
    op.create_index("ix_dataset_likes_user_id", "dataset_likes", ["user_id"], unique=False)
    op.create_table(
        "dataset_members",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("added_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('reader', 'annotator', 'maintainer')", name=op.f("ck_dataset_members_role")),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name=op.f("fk_dataset_members_dataset_id_datasets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("dataset_id", "user_id", name=op.f("pk_dataset_members")),
    )
    op.create_index("ix_dataset_members_user_id", "dataset_members", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dataset_members_user_id", table_name="dataset_members")
    op.drop_table("dataset_members")
    op.drop_index("ix_dataset_likes_user_id", table_name="dataset_likes")
    op.drop_table("dataset_likes")
    op.drop_index("ix_datasets_updated_at", table_name="datasets")
    op.drop_index(op.f("ix_datasets_created_by"), table_name="datasets")
    op.drop_table("datasets")
