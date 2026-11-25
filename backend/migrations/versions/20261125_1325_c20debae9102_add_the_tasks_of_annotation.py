"""add the tasks of annotation

Revision ID: c20debae9102
Revises: 2e9503b9d8b9
Create Date: 2026-11-25 13:25:54.094439
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c20debae9102"
down_revision: str | None = "2e9503b9d8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annotation_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("jsonb_typeof(config) = 'object'", name=op.f("ck_annotation_tasks_config")),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_annotation_tasks_status")),
        sa.CheckConstraint(
            "type IN ('classification', 'ner', 'qa', 'regression', 'row_label', 'cell_review', 'column_schema', 'image_detection', 'image_segmentation', 'image_polyline', 'image_keypoints', 'image_classification', 'image_caption', 'image_vqa', 'audio_classification', 'audio_segments', 'audio_transcription', 'audio_caption', 'video_classification', 'video_segments', 'video_tracking', 'video_caption', 'timeseries_classification', 'timeseries_segments', 'timeseries_caption')",
            name=op.f("ck_annotation_tasks_type"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name=op.f("fk_annotation_tasks_dataset_id_datasets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotation_tasks")),
        sa.UniqueConstraint("dataset_id", "name", name="uq_annotation_tasks_name"),
    )
    op.create_index(op.f("ix_annotation_tasks_dataset_id"), "annotation_tasks", ["dataset_id"], unique=False)
    op.create_table(
        "annotation_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["annotation_tasks.id"],
            name=op.f("fk_annotation_labels_task_id_annotation_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotation_labels")),
    )
    op.create_index(op.f("ix_annotation_labels_task_id"), "annotation_labels", ["task_id"], unique=False)
    op.create_index(
        "uq_annotation_labels_name",
        "annotation_labels",
        ["task_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "annotations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("split", sa.String(length=50), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("annotator", sa.String(length=255), nullable=False),
        sa.Column("annotator_username", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="submitted", nullable=False),
        sa.Column("source", sa.String(length=10), server_default="human", nullable=False),
        sa.Column("label_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source IN ('human', 'model')", name=op.f("ck_annotations_source")),
        sa.CheckConstraint("status IN ('draft', 'submitted')", name=op.f("ck_annotations_status")),
        sa.CheckConstraint("row_index >= 0", name=op.f("ck_annotations_row_index")),
        sa.ForeignKeyConstraint(
            ["label_id"], ["annotation_labels.id"], name=op.f("fk_annotations_label_id_annotation_labels")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["annotation_tasks.id"],
            name=op.f("fk_annotations_task_id_annotation_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotations")),
        sa.UniqueConstraint("task_id", "split", "row_index", "annotator", name="uq_annotations_row"),
    )
    op.create_index("ix_annotations_task_id_annotator", "annotations", ["task_id", "annotator"], unique=False)
    op.create_index(
        "ix_annotations_task_id_split_row_index", "annotations", ["task_id", "split", "row_index"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_annotations_task_id_split_row_index", table_name="annotations")
    op.drop_index("ix_annotations_task_id_annotator", table_name="annotations")
    op.drop_table("annotations")
    op.drop_index(
        "uq_annotation_labels_name", table_name="annotation_labels", postgresql_where=sa.text("deleted_at IS NULL")
    )
    op.drop_index(op.f("ix_annotation_labels_task_id"), table_name="annotation_labels")
    op.drop_table("annotation_labels")
    op.drop_index(op.f("ix_annotation_tasks_dataset_id"), table_name="annotation_tasks")
    op.drop_table("annotation_tasks")
