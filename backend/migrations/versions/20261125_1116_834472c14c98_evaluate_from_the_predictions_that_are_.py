"""evaluate from the predictions that are sent

Revision ID: 834472c14c98
Revises: 387c8df9253f
Create Date: 2026-11-25 11:16:57.179822
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "834472c14c98"
down_revision: str | None = "387c8df9253f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # What a client sent as values is no longer published: the platform computes the metrics from predictions. The
    # feature was a few days old, there is nothing to carry over.
    op.execute("DELETE FROM model_evaluations")
    for name in ("source", "status", "submitted_is_done"):
        op.drop_constraint(op.f(f"ck_model_evaluations_{name}"), "model_evaluations", type_="check")
    op.add_column("model_evaluations", sa.Column("predictions_key", sa.String(length=512), nullable=True))
    op.add_column("model_evaluations", sa.Column("predictions_format", sa.String(length=10), nullable=True))
    op.add_column("model_evaluations", sa.Column("predictions_size", sa.BigInteger(), nullable=True))
    op.add_column("model_evaluations", sa.Column("key_column", sa.String(length=255), nullable=True))
    op.add_column(
        "model_evaluations",
        sa.Column("prediction_column", sa.String(length=255), server_default="prediction", nullable=False),
    )
    op.add_column("model_evaluations", sa.Column("multipart_id", sa.String(length=512), nullable=True))
    op.add_column("model_evaluations", sa.Column("part_size", sa.Integer(), nullable=True))
    op.add_column("model_evaluations", sa.Column("parts_count", sa.Integer(), nullable=True))
    op.add_column("model_evaluations", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column(
        "model_evaluations",
        "source",
        existing_type=sa.VARCHAR(length=10),
        type_=sa.String(length=12),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_model_evaluations_source"), "model_evaluations", "source IN ('predictions', 'endpoint', 'inference')"
    )
    op.create_check_constraint(
        op.f("ck_model_evaluations_status"),
        "model_evaluations",
        "status IN ('uploading', 'pending', 'running', 'done', 'failed', 'stopped')",
    )
    op.create_check_constraint(
        op.f("ck_model_evaluations_format"),
        "model_evaluations",
        "predictions_format IS NULL OR predictions_format IN ('jsonl', 'csv', 'parquet')",
    )
    op.create_check_constraint(
        op.f("ck_model_evaluations_uploading_has_upload"),
        "model_evaluations",
        "status <> 'uploading' OR (multipart_id IS NOT NULL AND expires_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM model_evaluations")
    for name in ("source", "status", "format", "uploading_has_upload"):
        op.drop_constraint(op.f(f"ck_model_evaluations_{name}"), "model_evaluations", type_="check")
    op.alter_column(
        "model_evaluations",
        "source",
        existing_type=sa.String(length=12),
        type_=sa.VARCHAR(length=10),
        existing_nullable=False,
    )
    op.drop_column("model_evaluations", "expires_at")
    op.drop_column("model_evaluations", "parts_count")
    op.drop_column("model_evaluations", "part_size")
    op.drop_column("model_evaluations", "multipart_id")
    op.drop_column("model_evaluations", "prediction_column")
    op.drop_column("model_evaluations", "key_column")
    op.drop_column("model_evaluations", "predictions_size")
    op.drop_column("model_evaluations", "predictions_format")
    op.drop_column("model_evaluations", "predictions_key")
    op.create_check_constraint(
        op.f("ck_model_evaluations_source"), "model_evaluations", "source IN ('measured', 'submitted')"
    )
    op.create_check_constraint(
        op.f("ck_model_evaluations_status"),
        "model_evaluations",
        "status IN ('pending', 'running', 'done', 'failed', 'stopped')",
    )
    op.create_check_constraint(
        op.f("ck_model_evaluations_submitted_is_done"), "model_evaluations", "source <> 'submitted' OR status = 'done'"
    )
