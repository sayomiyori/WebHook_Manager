"""Add durable legacy delivery retry and notification schedules.

Revision ID: 6e2f8a1c9b04
Revises: 3cc3bb772105
"""

import sqlalchemy as sa
from alembic import op

revision = "6e2f8a1c9b04"
down_revision = "3cc3bb772105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_attempts",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "delivery_attempts",
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Retain scheduled manual retries; old failures wait the existing HTTP backoff.
    op.execute(
        "UPDATE delivery_attempts SET next_attempt_at = CASE "
        "WHEN status = 'FAILED' THEN updated_at + make_interval(secs => CASE "
        "WHEN attempt_number <= 2 THEN 10 WHEN attempt_number = 3 THEN 30 "
        "WHEN attempt_number = 4 THEN 120 WHEN attempt_number = 5 THEN 600 "
        "ELSE 3600 END) ELSE attempted_at END "
        "WHERE status IN ('PENDING', 'RETRYING', 'FAILED')"
    )
    op.execute(
        "UPDATE delivery_attempts SET next_dispatch_at = next_attempt_at "
        "WHERE next_attempt_at IS NOT NULL"
    )
    op.create_index(
        "ix_delivery_attempts_dispatch_due",
        "delivery_attempts",
        ["status", "next_dispatch_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_attempts_dispatch_due", table_name="delivery_attempts")
    op.drop_column("delivery_attempts", "next_dispatch_at")
    op.drop_column("delivery_attempts", "next_attempt_at")
