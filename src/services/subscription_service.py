from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.domain.entities.subscription import Subscription
from src.domain.interfaces.repositories import SubscriptionRepository


class SubscriptionService:
    def __init__(self, repo: SubscriptionRepository) -> None:
        self._repo = repo

    async def get(self, subscription_id: UUID) -> Subscription | None:
        return await self._repo.get_by_id(subscription_id)

    async def list_by_owner(
        self, owner_id: UUID, *, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        return await self._repo.get_by_owner(owner_id, cursor, limit)

    async def list_by_endpoint(
        self, endpoint_id: UUID, *, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        return await self._repo.get_by_endpoint(endpoint_id, cursor, limit)

    async def list_by_source(
        self, source_id: UUID, *, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        return await self._repo.get_by_source(source_id, cursor, limit)

    async def create(
        self,
        *,
        owner_id: UUID,
        endpoint_id: UUID,
        source_id: UUID,
        event_type_filter: list[str] | None,
        is_active: bool = True,
    ) -> Subscription:
        now = datetime.now(UTC)
        subscription = Subscription(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            endpoint_id=endpoint_id,
            source_id=source_id,
            owner_id=owner_id,
            event_type_filter=event_type_filter or ["*"],
            is_active=is_active,
        )
        return await self._repo.create(subscription)

    async def update(self, subscription: Subscription) -> Subscription:
        updated = Subscription(
            id=subscription.id,
            created_at=subscription.created_at,
            updated_at=datetime.now(UTC),
            endpoint_id=subscription.endpoint_id,
            source_id=subscription.source_id,
            owner_id=subscription.owner_id,
            event_type_filter=list(subscription.event_type_filter),
            is_active=subscription.is_active,
        )
        return await self._repo.update(updated)

    async def delete(self, subscription_id: UUID) -> None:
        await self._repo.delete(subscription_id)

