from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.subscription import Subscription
from src.domain.interfaces.repositories import SubscriptionRepository
from src.infrastructure.db.mappers import subscription_to_entity, subscription_to_model
from src.infrastructure.db.models.subscription import SubscriptionModel
from src.infrastructure.db.repositories._base import clamp_limit


class PostgresSubscriptionRepository(SubscriptionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> Subscription | None:
        model = await self._session.get(SubscriptionModel, id)
        return None if model is None else subscription_to_entity(model)

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        lim = clamp_limit(limit)
        stmt = select(SubscriptionModel).where(SubscriptionModel.owner_id == owner_id)
        if cursor is not None:
            stmt = stmt.where(SubscriptionModel.id > cursor)
        stmt = stmt.order_by(SubscriptionModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_entity(m) for m in rows]

    async def get_by_endpoint(
        self, endpoint_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        lim = clamp_limit(limit)
        stmt = select(SubscriptionModel).where(
            SubscriptionModel.endpoint_id == endpoint_id
        )
        if cursor is not None:
            stmt = stmt.where(SubscriptionModel.id > cursor)
        stmt = stmt.order_by(SubscriptionModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_entity(m) for m in rows]

    async def get_by_source(
        self, source_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        lim = clamp_limit(limit)
        stmt = select(SubscriptionModel).where(SubscriptionModel.source_id == source_id)
        if cursor is not None:
            stmt = stmt.where(SubscriptionModel.id > cursor)
        stmt = stmt.order_by(SubscriptionModel.id.asc()).limit(lim)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_entity(m) for m in rows]

    async def create(self, subscription: Subscription) -> Subscription:
        model = subscription_to_model(subscription)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return subscription_to_entity(model)

    async def update(self, subscription: Subscription) -> Subscription:
        model = subscription_to_model(subscription)
        merged = await self._session.merge(model)
        await self._session.commit()
        await self._session.refresh(merged)
        return subscription_to_entity(merged)

    async def delete(self, id: UUID) -> None:
        await self._session.execute(
            delete(SubscriptionModel).where(SubscriptionModel.id == id)
        )
        await self._session.commit()

