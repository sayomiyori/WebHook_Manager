"""Serialize admission and retain manual delivery resolution metadata."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8f3b1c6d2a90"
down_revision = "6e2f8a1c9b04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text("""
        SELECT 1 FROM webhook_events
        WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''
        GROUP BY source_id, idempotency_key HAVING count(*) > 1 LIMIT 1
    """)
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Historical duplicate admission keys require operator reconciliation"
        )
    op.create_index(
        "uq_webhook_events_source_idempotency",
        "webhook_events",
        ["source_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(
            "idempotency_key IS NOT NULL AND idempotency_key <> ''"
        ),
    )
    op.add_column(
        "delivery_attempts", sa.Column("retried_from_id", postgresql.UUID(as_uuid=True))
    )
    op.create_foreign_key(
        "fk_delivery_retried_from",
        "delivery_attempts",
        "delivery_attempts",
        ["retried_from_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_delivery_retried_from", "delivery_attempts", ["retried_from_id"]
    )
    op.add_column(
        "delivery_attempts", sa.Column("resolved_by", postgresql.UUID(as_uuid=True))
    )
    op.add_column(
        "delivery_attempts", sa.Column("resolved_at", sa.DateTime(timezone=True))
    )
    op.add_column("delivery_attempts", sa.Column("resolution", sa.String(32)))
    op.add_column(
        "delivery_attempts", sa.Column("resolution_reference", sa.String(128))
    )


def downgrade() -> None:
    op.drop_column("delivery_attempts", "resolution_reference")
    op.drop_column("delivery_attempts", "resolution")
    op.drop_column("delivery_attempts", "resolved_at")
    op.drop_column("delivery_attempts", "resolved_by")
    op.drop_constraint("uq_delivery_retried_from", "delivery_attempts", type_="unique")
    op.drop_constraint(
        "fk_delivery_retried_from", "delivery_attempts", type_="foreignkey"
    )
    op.drop_column("delivery_attempts", "retried_from_id")
    op.drop_index("uq_webhook_events_source_idempotency", table_name="webhook_events")
