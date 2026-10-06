from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class TelegramIngressEventModel(Base):
    __tablename__ = "telegram_ingress_events"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    bot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("telegram_bots.id")
    )
    update_id: Mapped[int] = mapped_column(BigInteger)
    raw: Mapped[dict[str, object]] = mapped_column(JSONB)
    digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    envelope: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("bot_id", "update_id", name="uq_telegram_ingress_bot_update"),
        CheckConstraint(
            "state IN ('accepted','ignored')", name="ck_telegram_ingress_state"
        ),
        Index("ix_telegram_ingress_scope_id", "tenant_id", "bot_id", "id"),
    )
