"""api key unique prefix

Revision ID: 3cd0dbb0eef9
Revises: ae7c0da22271
Create Date: 2026-03-18 14:06:51.851614

"""

from __future__ import annotations

from alembic import op

revision = "3cd0dbb0eef9"
down_revision = "ae7c0da22271"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")
    op.create_index(
        op.f("ix_api_keys_key_prefix"),
        "api_keys",
        ["key_prefix"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")
    op.create_index(
        op.f("ix_api_keys_key_prefix"),
        "api_keys",
        ["key_prefix"],
        unique=False,
    )

