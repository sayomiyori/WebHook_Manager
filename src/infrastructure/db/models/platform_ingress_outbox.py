from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class PlatformIngressOutboxModel(Base):
    __tablename__ = "platform_ingress_outbox"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    ingress_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("telegram_ingress_events.id")
    )
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    bot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("telegram_bots.id")
    )
    state: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claim_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    claim_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("ingress_id", name="uq_platform_outbox_ingress"),
        CheckConstraint(
            "state IN ('pending','processing','published','failed','cancelled')",
            name="ck_platform_outbox_state",
        ),
        CheckConstraint(
            "attempts >= 0 AND attempts <= 100", name="ck_platform_outbox_attempts"
        ),
        Index("ix_platform_outbox_due", "state", "next_attempt_at", "claim_deadline"),
    )
