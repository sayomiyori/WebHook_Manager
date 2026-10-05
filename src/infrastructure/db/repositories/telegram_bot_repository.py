from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models.telegram_bot import TelegramBotModel


class TelegramBotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, bot_id: UUID, tenant_id: UUID | None = None
    ) -> TelegramBotModel | None:
        stmt = select(TelegramBotModel).where(TelegramBotModel.id == bot_id)
        if tenant_id is not None:
            stmt = stmt.where(TelegramBotModel.tenant_id == tenant_id)
        return (
            await self.session.execute(stmt.execution_options(populate_existing=True))
        ).scalar_one_or_none()

    async def list(
        self, tenant_id: UUID, cursor: UUID | None, limit: int
    ) -> list[TelegramBotModel]:
        stmt = select(TelegramBotModel).where(TelegramBotModel.tenant_id == tenant_id)
        if cursor is not None:
            stmt = stmt.where(TelegramBotModel.id > cursor)
        return list(
            (
                await self.session.execute(
                    stmt.order_by(TelegramBotModel.id).limit(limit)
                )
            ).scalars()
        )

    async def deactivate(self, bot_id: UUID, tenant_id: UUID) -> None:
        await self.session.execute(
            update(TelegramBotModel)
            .where(
                TelegramBotModel.id == bot_id,
                TelegramBotModel.tenant_id == tenant_id,
                TelegramBotModel.is_active.is_(True),
            )
            .values(is_active=False, updated_at=func.now())
        )
