"""add Telegram answer intents

Revision ID: 3cc3bb772105
Revises: 9a3c012bd7ef
Create Date: 2026-10-06 21:02:33.882194

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "3cc3bb772105"
down_revision = "9a3c012bd7ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The referenced scope must exist before the answer foreign key.
    op.create_unique_constraint(
        "uq_telegram_ingress_scope",
        "telegram_ingress_events",
        ["id", "tenant_id", "bot_id"],
    )
    op.create_table(
        "telegram_answers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("ingress_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("bot_id", sa.UUID(), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "state", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claim_id", sa.UUID(), nullable=True),
        sa.Column("claim_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'processing' AND claim_id IS NOT NULL "
            "AND claim_deadline IS NOT NULL) OR (state <> 'processing' "
            "AND claim_id IS NULL AND claim_deadline IS NULL)",
            name="ck_telegram_answer_claim",
        ),
        sa.CheckConstraint(
            "state <> 'succeeded' OR (message_id IS NOT NULL "
            "AND message_id > 0 AND send_started_at IS NOT NULL)",
            name="ck_telegram_answer_success",
        ),
        sa.CheckConstraint(
            "state IN ('pending','processing','succeeded','failed',"
            "'unknown','cancelled')",
            name="ck_telegram_answer_state",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 5", name="ck_telegram_answer_attempts"
        ),
        sa.ForeignKeyConstraint(
            ["ingress_id", "tenant_id", "bot_id"],
            [
                "telegram_ingress_events.id",
                "telegram_ingress_events.tenant_id",
                "telegram_ingress_events.bot_id",
            ],
            name="fk_telegram_answer_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_telegram_answer_event"),
        sa.UniqueConstraint("ingress_id", name="uq_telegram_answer_ingress"),
    )
    op.create_index(
        "ix_telegram_answer_due",
        "telegram_answers",
        ["state", "next_attempt_at", "claim_deadline"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_answer_scope",
        "telegram_answers",
        ["tenant_id", "bot_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_answer_scope", table_name="telegram_answers")
    op.drop_index("ix_telegram_answer_due", table_name="telegram_answers")
    op.drop_table("telegram_answers")
    op.drop_constraint(
        "uq_telegram_ingress_scope", "telegram_ingress_events", type_="unique"
    )
