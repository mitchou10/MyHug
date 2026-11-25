"""add the access tokens

Revision ID: 251ee42c2344
Revises: 8ba500b3e2a4
Create Date: 2026-11-25 08:35:23.318868
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "251ee42c2344"
down_revision: str | None = "8ba500b3e2a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("email", sa.String(length=255), server_default="", nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=5), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('read', 'write')", name=op.f("ck_access_tokens_scope")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_access_tokens_token_hash")),
    )
    op.create_index("ix_access_tokens_user_id", "access_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_access_tokens_user_id", table_name="access_tokens")
    op.drop_table("access_tokens")
