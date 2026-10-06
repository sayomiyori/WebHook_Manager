from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.db.base import Base

if TYPE_CHECKING:
    from src.infrastructure.db.models.telegram_bot_webhook import (
        TelegramBotWebhookModel,
    )


class TelegramBotModel(Base):
    __tablename__ = "telegram_bots"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(128))
    telegram_bot_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(128))
    credentials_encrypted: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    webhook: Mapped[TelegramBotWebhookModel | None] = relationship(lazy="selectin")

    @property
    def webhook_status(self) -> str:
        return self.webhook.effective_state if self.webhook else "not_configured"

    __table_args__ = (
        UniqueConstraint("telegram_bot_id", name="uq_telegram_bots_telegram_bot_id"),
        CheckConstraint(
            "telegram_bot_id > 0", name="ck_telegram_bots_positive_identity"
        ),
        Index("ix_telegram_bots_tenant_id_id", "tenant_id", "id"),
    )
