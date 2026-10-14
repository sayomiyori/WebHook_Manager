"""Keep legacy request quotas independent of the notification broker."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c42d8e91a730"
down_revision = "6e2f8a1c9b04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legacy_rate_limits",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column(
            "timestamps", postgresql.ARRAY(sa.DateTime(timezone=True)), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_legacy_rate_limits_expires_at", "legacy_rate_limits", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_legacy_rate_limits_expires_at", table_name="legacy_rate_limits")
    op.drop_table("legacy_rate_limits")
