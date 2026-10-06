from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class TelegramAnswerModel(Base):
    __tablename__ = "telegram_answers"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    ingress_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    job_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    bot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    envelope: Mapped[dict[str, object]] = mapped_column(JSONB)
    digest: Mapped[str] = mapped_column(String(64))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claim_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    claim_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_telegram_answer_event"),
        UniqueConstraint("ingress_id", name="uq_telegram_answer_ingress"),
        ForeignKeyConstraint(
            ["ingress_id", "tenant_id", "bot_id"],
            [
                "telegram_ingress_events.id",
                "telegram_ingress_events.tenant_id",
                "telegram_ingress_events.bot_id",
            ],
            name="fk_telegram_answer_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('pending','processing','succeeded','failed',"
            "'unknown','cancelled')",
            name="ck_telegram_answer_state",
        ),
        CheckConstraint(
            "attempts >= 0 AND attempts <= 5", name="ck_telegram_answer_attempts"
        ),
        CheckConstraint(
            "(state = 'processing' AND claim_id IS NOT NULL "
            "AND claim_deadline IS NOT NULL) OR (state <> 'processing' "
            "AND claim_id IS NULL AND claim_deadline IS NULL)",
            name="ck_telegram_answer_claim",
        ),
        CheckConstraint(
            "state <> 'succeeded' OR (message_id IS NOT NULL "
            "AND message_id > 0 AND send_started_at IS NOT NULL)",
            name="ck_telegram_answer_success",
        ),
        Index("ix_telegram_answer_scope", "tenant_id", "bot_id", "id"),
        Index("ix_telegram_answer_due", "state", "next_attempt_at", "claim_deadline"),
    )
