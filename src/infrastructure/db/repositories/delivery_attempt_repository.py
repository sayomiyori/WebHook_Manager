from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.core.constants import DELIVERY_RETRY_DELAYS_SECONDS
from src.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from src.domain.entities.delivery import DeliveryAttempt
from src.domain.enums import DeliveryStatus
from src.domain.interfaces.repositories import DeliveryAttemptRepository
from src.infrastructure.db.mappers import (
    delivery_attempt_to_entity,
    delivery_attempt_to_model,
)
from src.infrastructure.db.models.delivery_attempt import DeliveryAttemptModel
from src.infrastructure.db.models.endpoint import EndpointModel
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

    async def schedule_retry(
        self, delivery_id: UUID, attempt_number: int
    ) -> DeliveryAttempt:
        row = await self._session.get(
            DeliveryAttemptModel,
            delivery_id,
            with_for_update=True,
            populate_existing=True,
        )
        if row is None:
            raise NotFoundError()
        if row.status not in (DeliveryStatus.FAILED, DeliveryStatus.EXHAUSTED):
            raise ConflictError()
        existing = await self._session.scalar(
            select(DeliveryAttemptModel).where(
                DeliveryAttemptModel.retried_from_id == row.id
            )
        )
        if existing is not None:
            return delivery_attempt_to_entity(existing)
        if attempt_number != row.attempt_number + 1:
            raise ConflictError()
        now = datetime.now(UTC)
        delay = DELIVERY_RETRY_DELAYS_SECONDS[
            min(max(attempt_number - 1, 0), len(DELIVERY_RETRY_DELAYS_SECONDS) - 1)
        ]
        due = now + timedelta(seconds=delay)
        retry = DeliveryAttemptModel(
            id=uuid4(),
            event_id=row.event_id,
            endpoint_id=row.endpoint_id,
            retried_from_id=row.id,
            attempt_number=attempt_number,
            status=DeliveryStatus.RETRYING,
            attempted_at=due,
            next_attempt_at=due,
            next_dispatch_at=due,
            created_at=now,
            updated_at=now,
        )
        row.status = DeliveryStatus.EXHAUSTED
        row.next_attempt_at = row.next_dispatch_at = None
        row.updated_at = now
        self._session.add(retry)
        await self._session.commit()
        return delivery_attempt_to_entity(retry)

    async def resolve_claim(
        self,
        delivery_id: UUID,
        owner_id: UUID,
        attempted_at: datetime,
        outcome: Literal["delivered", "not_delivered"],
        reference: str,
    ) -> DeliveryAttempt:
        row = await self._session.get(
            DeliveryAttemptModel,
            delivery_id,
            with_for_update=True,
            populate_existing=True,
        )
        if row is None:
            raise NotFoundError()
        endpoint = await self._session.get(EndpointModel, row.endpoint_id)
        if endpoint is None or endpoint.owner_id != owner_id:
            raise ForbiddenError()
        now = (await self._session.execute(select(func.clock_timestamp()))).scalar_one()
        if (
            row.status != DeliveryStatus.DELIVERING
            or row.attempted_at != attempted_at
            or now - row.attempted_at < timedelta(seconds=60)
        ):
            raise ConflictError()
        row.status = (
            DeliveryStatus.SUCCESS
            if outcome == "delivered"
            else DeliveryStatus.EXHAUSTED
        )
        row.error_message = "Operator confirmed " + outcome
        row.next_attempt_at = row.next_dispatch_at = None
        row.resolved_by, row.resolved_at = owner_id, now
        row.resolution, row.resolution_reference = outcome, reference
        row.updated_at = now
        await self._session.commit()
        return delivery_attempt_to_entity(row)


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
