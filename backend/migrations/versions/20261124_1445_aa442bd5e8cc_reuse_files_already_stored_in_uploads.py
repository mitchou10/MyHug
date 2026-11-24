"""reuse files already stored in uploads

Revision ID: aa442bd5e8cc
Revises: bd435ae63867
Create Date: 2026-11-24 14:45:03.719198
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "aa442bd5e8cc"
down_revision: str | None = "bd435ae63867"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dataset_upload_files", sa.Column("sha256", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_dataset_files_sha256",
        "dataset_files",
        ["sha256"],
        unique=False,
        postgresql_where=sa.text("sha256 IS NOT NULL"),
    )
    # A file that is already stored in the dataset is not sent: no upload in parts, so no identifier and no parts.
    op.alter_column("dataset_upload_files", "multipart_id", existing_type=sa.VARCHAR(length=512), nullable=True)
    op.drop_constraint(op.f("ck_dataset_upload_files_sizes"), "dataset_upload_files", type_="check")
    op.create_check_constraint(
        op.f("ck_dataset_upload_files_sizes"),
        "dataset_upload_files",
        "size_bytes > 0 AND part_size >= 0 AND parts_count >= 0",
    )


def downgrade() -> None:
    # The files that were not sent have no upload in parts to go back to: they are of no use without this column.
    op.drop_index("ix_dataset_files_sha256", table_name="dataset_files", postgresql_where=sa.text("sha256 IS NOT NULL"))
    op.execute("DELETE FROM dataset_upload_files WHERE multipart_id IS NULL")
    op.drop_constraint(op.f("ck_dataset_upload_files_sizes"), "dataset_upload_files", type_="check")
    op.create_check_constraint(
        op.f("ck_dataset_upload_files_sizes"),
        "dataset_upload_files",
        "size_bytes > 0 AND part_size > 0 AND parts_count > 0",
    )
    op.alter_column("dataset_upload_files", "multipart_id", existing_type=sa.VARCHAR(length=512), nullable=False)
    op.drop_column("dataset_upload_files", "sha256")
