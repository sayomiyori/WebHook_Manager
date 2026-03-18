from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.webhook_event import WebhookEvent
from src.domain.interfaces.repositories import WebhookEventRepository
from src.infrastructure.db.mappers import (
    webhook_event_to_entity,
    webhook_event_to_model,
)
from src.infrastructure.db.models.webhook_event import WebhookEventModel
from src.infrastructure.db.repositories._base import clamp_limit


class PostgresWebhookEventRepository(WebhookEventRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> WebhookEvent | None:
        model = await self._session.get(WebhookEventModel, id)
        return None if model is None else webhook_event_to_entity(model)

    async def get_by_source(
        self, source_id: UUID, cursor: UUID | None, limit: int
    ) -> list[WebhookEvent]:
        lim = clamp_limit(limit)
        stmt = select(WebhookEventModel).where(WebhookEventModel.source_id == source_id)
        if cursor is not None:
            stmt = stmt.where(WebhookEventModel.id > cursor)
        stmt = stmt.order_by(WebhookEventModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [webhook_event_to_entity(m) for m in rows]

    async def create(self, event: WebhookEvent) -> WebhookEvent:
        model = webhook_event_to_model(event)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return webhook_event_to_entity(model)

    async def update(self, event: WebhookEvent) -> WebhookEvent:
        model = webhook_event_to_model(event)
        merged = await self._session.merge(model)
        await self._session.commit()
        await self._session.refresh(merged)
        return webhook_event_to_entity(merged)

    async def delete(self, id: UUID) -> None:
        await self._session.execute(
            delete(WebhookEventModel).where(WebhookEventModel.id == id)
        )
        await self._session.commit()

