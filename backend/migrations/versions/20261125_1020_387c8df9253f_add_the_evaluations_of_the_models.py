"""add the evaluations of the models

Revision ID: 387c8df9253f
Revises: 251ee42c2344
Create Date: 2026-11-25 10:20:22.037568
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "387c8df9253f"
down_revision: str | None = "251ee42c2344"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("dataset_address", sa.String(length=201), nullable=True),
        sa.Column("dataset_version", sa.Integer(), nullable=True),
        sa.Column("split", sa.String(length=50), nullable=True),
        sa.Column("input_column", sa.String(length=255), nullable=True),
        sa.Column("target_column", sa.String(length=255), nullable=True),
        sa.Column("items", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "results", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "shown", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("note", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "jsonb_typeof(results) = 'object' AND jsonb_typeof(shown) = 'array'",
            name=op.f("ck_model_evaluations_json_shapes"),
        ),
        sa.CheckConstraint(
            "source <> 'submitted' OR status = 'done'", name=op.f("ck_model_evaluations_submitted_is_done")
        ),
        sa.CheckConstraint("source IN ('measured', 'submitted')", name=op.f("ck_model_evaluations_source")),
        sa.CheckConstraint(
            "status <> 'done' OR results <> '{}'::jsonb", name=op.f("ck_model_evaluations_done_has_results")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'stopped')", name=op.f("ck_model_evaluations_status")
        ),
        sa.CheckConstraint("items IS NULL OR items >= 0", name=op.f("ck_model_evaluations_items")),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name=op.f("fk_model_evaluations_dataset_id_datasets"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["models.id"], name=op.f("fk_model_evaluations_model_id_models"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["model_versions.id"],
            name=op.f("fk_model_evaluations_version_id_model_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_evaluations")),
    )
    op.create_index(
        "ix_model_evaluations_model_id_created_at", "model_evaluations", ["model_id", "created_at"], unique=False
    )
    op.create_index("ix_model_evaluations_version_id", "model_evaluations", ["version_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_model_evaluations_version_id", table_name="model_evaluations")
    op.drop_index("ix_model_evaluations_model_id_created_at", table_name="model_evaluations")
    op.drop_table("model_evaluations")
