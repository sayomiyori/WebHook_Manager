from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.domain.entities.subscription import Subscription
from src.domain.entities.webhook_event import WebhookEvent
from src.domain.interfaces.repositories import (
    SubscriptionRepository,
    WebhookEventRepository,
)
from src.services.event_service import EventService


class FakeEventRepo(WebhookEventRepository):
    def __init__(self) -> None:
        self._items: dict[UUID, WebhookEvent] = {}
        self._idem: dict[tuple[UUID, str], UUID] = {}

    async def get_by_id(self, id: UUID) -> WebhookEvent | None:
        return self._items.get(id)

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[WebhookEvent]:
        # For unit tests we don't model ownership in events; return all.
        items = list(self._items.values())
        items.sort(key=lambda e: e.id)
        if cursor is not None:
            items = [e for e in items if e.id > cursor]
        return items[:limit]

    async def get_by_source(
        self, source_id: UUID, cursor: UUID | None, limit: int
    ) -> list[WebhookEvent]:
        items = [e for e in self._items.values() if e.source_id == source_id]
        items.sort(key=lambda e: e.id)
        if cursor is not None:
            items = [e for e in items if e.id > cursor]
        return items[:limit]

    async def get_by_idempotency_key(
        self, source_id: UUID, idempotency_key: str
    ) -> WebhookEvent | None:
        key = (source_id, idempotency_key)
        event_id = self._idem.get(key)
        return None if event_id is None else self._items.get(event_id)

    async def create(self, event: WebhookEvent) -> WebhookEvent:
        self._items[event.id] = event
        if event.idempotency_key:
            self._idem[(event.source_id, event.idempotency_key)] = event.id
        return event

    async def update(self, event: WebhookEvent) -> WebhookEvent:
        self._items[event.id] = event
        return event

    async def delete(self, id: UUID) -> None:
        self._items.pop(id, None)


class FakeSubscriptionRepo(SubscriptionRepository):
    def __init__(self, items: list[Subscription]) -> None:
        self._items = items

    async def get_by_id(self, id: UUID) -> Subscription | None:
        for s in self._items:
            if s.id == id:
                return s
        return None

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        items = [s for s in self._items if s.owner_id == owner_id]
        items.sort(key=lambda s: s.id)
        if cursor is not None:
            items = [s for s in items if s.id > cursor]
        return items[:limit]

    async def get_by_endpoint(
        self, endpoint_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        items = [s for s in self._items if s.endpoint_id == endpoint_id]
        items.sort(key=lambda s: s.id)
        if cursor is not None:
            items = [s for s in items if s.id > cursor]
        return items[:limit]

    async def get_by_source(
        self, source_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]:
        items = [s for s in self._items if s.source_id == source_id]
        items.sort(key=lambda s: s.id)
        if cursor is not None:
            items = [s for s in items if s.id > cursor]
        return items[:limit]

    async def create(self, subscription: Subscription) -> Subscription:
        self._items.append(subscription)
        return subscription

    async def update(self, subscription: Subscription) -> Subscription:
        return subscription

    async def delete(self, id: UUID) -> None:
        self._items = [s for s in self._items if s.id != id]


@pytest.mark.asyncio
async def test_ingest_idempotency_returns_duplicate() -> None:
    events = FakeEventRepo()
    subs = FakeSubscriptionRepo([])
    svc = EventService(events, subs)

    source_id = uuid4()
    payload: dict[str, object] = {"a": 1}
    headers = {"h": "v"}
    idem = "idem-1"

    e1, dup1 = await svc.ingest_event(
        source_id, payload, headers, idem, "payment.created"
    )
    e2, dup2 = await svc.ingest_event(
        source_id, payload, headers, idem, "payment.created"
    )

    assert dup1 is False
    assert dup2 is True
    assert e1.id == e2.id


@pytest.mark.asyncio
async def test_matching_subscriptions_glob() -> None:
    owner_id = uuid4()
    source_id = uuid4()
    endpoint_id = uuid4()
    now = datetime.now(UTC)

    s_any = Subscription(
        id=UUID(int=1),
        created_at=now,
        updated_at=now,
        endpoint_id=endpoint_id,
        source_id=source_id,
        owner_id=owner_id,
        event_type_filter=["*"],
        is_active=True,
    )
    s_glob = Subscription(
        id=UUID(int=2),
        created_at=now,
        updated_at=now,
        endpoint_id=endpoint_id,
        source_id=source_id,
        owner_id=owner_id,
        event_type_filter=["payment.*"],
        is_active=True,
    )
    s_other = Subscription(
        id=UUID(int=3),
        created_at=now,
        updated_at=now,
        endpoint_id=endpoint_id,
        source_id=source_id,
        owner_id=owner_id,
        event_type_filter=["user.*"],
        is_active=True,
    )

    events = FakeEventRepo()
    subs = FakeSubscriptionRepo([s_any, s_glob, s_other])
    svc = EventService(events, subs)

    event = WebhookEvent(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        source_id=source_id,
        payload={},
        headers={},
        idempotency_key=None,
        event_type="payment.created",
        received_at=now,
    )

    matched = await svc.get_matching_subscriptions(event)
    matched_ids = {s.id for s in matched}
    assert matched_ids == {UUID(int=1), UUID(int=2)}

