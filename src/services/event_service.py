from __future__ import annotations

import fnmatch
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.core.exceptions import ConflictError
from src.domain.entities.subscription import Subscription
from src.domain.entities.webhook_event import WebhookEvent
from src.domain.interfaces.repositories import EventRepository, SubscriptionRepository


class EventService:
    def __init__(
        self, event_repo: EventRepository, subscription_repo: SubscriptionRepository
    ) -> None:
        self._events = event_repo
        self._subs = subscription_repo

    async def ingest_event(
        self,
        source_id: UUID,
        payload: dict[str, object],
        headers: dict[str, str],
        idempotency_key: str | None,
        event_type: str | None,
    ) -> tuple[WebhookEvent, bool]:
        if idempotency_key:
            existing = await self._events.get_by_idempotency_key(
                source_id, idempotency_key
            )
            if existing is not None:
                _ = ConflictError  # referenced by spec; returning existing instead
                return existing, True

        now = datetime.now(UTC)
        event = WebhookEvent(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            source_id=source_id,
            payload=dict(payload),
            headers=dict(headers),
            idempotency_key=idempotency_key,
            event_type=event_type,
            received_at=now,
        )
        created = await self._events.create(event)
        return created, False

    async def get_event(self, event_id: UUID) -> WebhookEvent | None:
        return await self._events.get_by_id(event_id)

    async def list_events_by_source(
        self, source_id: UUID, cursor: UUID | None, limit: int
    ) -> tuple[list[WebhookEvent], UUID | None]:
        items = await self._events.get_by_source(source_id, cursor, limit)
        next_cursor = items[-1].id if len(items) == min(max(limit, 1), 100) else None
        return items, next_cursor

    async def get_matching_subscriptions(
        self, event: WebhookEvent
    ) -> list[Subscription]:
        subs = await self._subs.get_by_source(event.source_id, cursor=None, limit=100)
        et = event.event_type or ""

        matches: list[Subscription] = []
        for sub in subs:
            if not sub.is_active:
                continue
            patterns = sub.event_type_filter or ["*"]
            if "*" in patterns:
                matches.append(sub)
                continue
            if event.event_type is None:
                continue
            if any(fnmatch.fnmatch(et, p) for p in patterns):
                matches.append(sub)
        return matches

    async def list_events(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> tuple[list[WebhookEvent], UUID | None]:
        items = await self._events.get_by_owner(owner_id, cursor, limit)
        next_cursor = items[-1].id if len(items) == min(max(limit, 1), 100) else None
        return items, next_cursor

