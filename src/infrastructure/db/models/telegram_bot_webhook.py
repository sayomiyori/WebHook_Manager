from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, case, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column

from src.infrastructure.db.base import Base


class TelegramBotWebhookModel(Base):
    __tablename__ = "telegram_bot_webhooks"

    bot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("telegram_bots.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    encrypted_secret: Mapped[str] = mapped_column(Text)
    secret_digest: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(
        String(32), default="configuring", server_default="configuring"
    )
    claim_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    claim_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_state: Mapped[str] = column_property(
        case(
            (
                (state == "configuring")
                & (
                    claim_deadline.is_(None)
                    | (claim_deadline <= func.clock_timestamp())
                ),
                "unknown",
            ),
            else_=state,
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "state IN ('configuring','configured','failed','unknown')",
            name="ck_telegram_webhook_state",
        ),
    )
