from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.domain.entities.delivery import DeliveryAttempt
from src.domain.enums import DeliveryStatus
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
        if attempt.status in (DeliveryStatus.PENDING, DeliveryStatus.RETRYING):
            model.next_attempt_at = attempt.attempted_at
            model.next_dispatch_at = attempt.attempted_at
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


def claim_due_deliveries(
    session: Session, batch_size: int = 100
) -> list[tuple[UUID, UUID, UUID]]:
    if not 1 <= batch_size <= 100:
        raise ValueError("Invalid scanner batch size")
    now = session.execute(select(func.clock_timestamp())).scalar_one()
    rows = session.scalars(
        select(DeliveryAttemptModel)
        .where(
            DeliveryAttemptModel.status.in_(
                (DeliveryStatus.PENDING, DeliveryStatus.FAILED, DeliveryStatus.RETRYING)
            ),
            DeliveryAttemptModel.next_attempt_at <= now,
            DeliveryAttemptModel.next_dispatch_at <= now,
        )
        .order_by(DeliveryAttemptModel.next_dispatch_at, DeliveryAttemptModel.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        # A lost publication or scanner recovers after this notification lease.
        row.next_dispatch_at = now + timedelta(seconds=60)
    session.flush()
    return [(row.id, row.event_id, row.endpoint_id) for row in rows]
