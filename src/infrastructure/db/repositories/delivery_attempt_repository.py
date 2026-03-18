from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.delivery import DeliveryAttempt
from src.domain.interfaces.repositories import DeliveryAttemptRepository
from src.infrastructure.db.mappers import (
    delivery_attempt_to_entity,
    delivery_attempt_to_model,
)
from src.infrastructure.db.models.delivery_attempt import DeliveryAttemptModel
from src.infrastructure.db.repositories._base import clamp_limit


class PostgresDeliveryAttemptRepository(DeliveryAttemptRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> DeliveryAttempt | None:
        model = await self._session.get(DeliveryAttemptModel, id)
        return None if model is None else delivery_attempt_to_entity(model)

    async def get_by_event(
        self, event_id: UUID, cursor: UUID | None, limit: int
    ) -> list[DeliveryAttempt]:
        lim = clamp_limit(limit)
        stmt = select(DeliveryAttemptModel).where(
            DeliveryAttemptModel.event_id == event_id
        )
        if cursor is not None:
            stmt = stmt.where(DeliveryAttemptModel.id > cursor)
        stmt = stmt.order_by(DeliveryAttemptModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [delivery_attempt_to_entity(m) for m in rows]

    async def create(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        model = delivery_attempt_to_model(attempt)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return delivery_attempt_to_entity(model)

    async def update(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        model = delivery_attempt_to_model(attempt)
        merged = await self._session.merge(model)
        await self._session.commit()
        await self._session.refresh(merged)
        return delivery_attempt_to_entity(merged)

    async def delete(self, id: UUID) -> None:
        await self._session.execute(
            delete(DeliveryAttemptModel).where(DeliveryAttemptModel.id == id)
        )
        await self._session.commit()

