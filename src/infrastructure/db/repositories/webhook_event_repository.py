from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.webhook_event import WebhookEvent
from src.domain.enums import DeliveryStatus
from src.domain.interfaces.repositories import WebhookEventRepository
from src.infrastructure.db.mappers import (
    webhook_event_to_entity,
    webhook_event_to_model,
)
from src.infrastructure.db.models.delivery_attempt import DeliveryAttemptModel
from src.infrastructure.db.models.source import SourceModel
from src.infrastructure.db.models.webhook_event import WebhookEventModel
from src.infrastructure.db.repositories._base import clamp_limit


class PostgresWebhookEventRepository(WebhookEventRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> WebhookEvent | None:
        model = await self._session.get(WebhookEventModel, id)
        return None if model is None else webhook_event_to_entity(model)

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[WebhookEvent]:
        lim = clamp_limit(limit)
        stmt = (
            select(WebhookEventModel)
            .join(SourceModel, WebhookEventModel.source_id == SourceModel.id)
            .where(SourceModel.owner_id == owner_id)
        )
        if cursor is not None:
            stmt = stmt.where(WebhookEventModel.id > cursor)
        stmt = stmt.order_by(WebhookEventModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [webhook_event_to_entity(m) for m in rows]

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

    async def get_by_idempotency_key(
        self, source_id: UUID, idempotency_key: str
    ) -> WebhookEvent | None:
        stmt = select(WebhookEventModel).where(
            WebhookEventModel.source_id == source_id,
            WebhookEventModel.idempotency_key == idempotency_key,
        )
        model = (await self._session.execute(stmt)).scalars().first()
        return None if model is None else webhook_event_to_entity(model)

    async def create(self, event: WebhookEvent) -> WebhookEvent:
        model = webhook_event_to_model(event)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return webhook_event_to_entity(model)

    async def create_admission(
        self, event: WebhookEvent, endpoint_ids: list[UUID]
    ) -> tuple[WebhookEvent, bool]:
        model = webhook_event_to_model(event)
        values = {
            column.name: getattr(model, column.name)
            for column in model.__table__.columns
        }
        statement = insert(WebhookEventModel).values(**values)
        if event.idempotency_key:
            statement = statement.on_conflict_do_nothing(
                index_elements=[
                    WebhookEventModel.source_id,
                    WebhookEventModel.idempotency_key,
                ],
                index_where=(WebhookEventModel.idempotency_key.is_not(None))
                & (WebhookEventModel.idempotency_key != ""),
            )
        inserted = await self._session.scalar(statement.returning(WebhookEventModel.id))
        if inserted is None:
            existing = await self.get_by_idempotency_key(
                event.source_id, event.idempotency_key or ""
            )
            if existing is None:
                raise RuntimeError("Admission conflict without existing event")
            return existing, True
        for endpoint_id in endpoint_ids:
            self._session.add(
                DeliveryAttemptModel(
                    id=uuid4(),
                    event_id=event.id,
                    endpoint_id=endpoint_id,
                    attempt_number=1,
                    status=DeliveryStatus.PENDING,
                    attempted_at=event.received_at,
                    next_attempt_at=event.received_at,
                    next_dispatch_at=event.received_at,
                    created_at=event.created_at,
                    updated_at=event.updated_at,
                )
            )
        # No accepted event exists without its complete durable fanout.
        await self._session.commit()
        return event, False

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
