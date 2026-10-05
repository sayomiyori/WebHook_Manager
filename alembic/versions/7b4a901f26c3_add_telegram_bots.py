"""Add tenant-scoped Telegram bot registrations.

Revision ID: 7b4a901f26c3
Revises: e6e39a93b58d
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "7b4a901f26c3"
down_revision = "e6e39a93b58d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_bots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("telegram_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(128), nullable=True),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_bot_id", name="uq_telegram_bots_telegram_bot_id"),
        sa.CheckConstraint(
            "telegram_bot_id > 0", name="ck_telegram_bots_positive_identity"
        ),
    )
    op.create_index(
        "ix_telegram_bots_tenant_id_id", "telegram_bots", ["tenant_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_bots_tenant_id_id", table_name="telegram_bots")
    op.drop_table("telegram_bots")
