from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.core.exceptions import ForbiddenError
from src.domain.entities.delivery import DeliveryAttempt
from src.domain.entities.endpoint import Endpoint
from src.domain.enums import DeliveryStatus
from src.domain.interfaces.repositories import (
    DeliveryAttemptRepository,
    EndpointRepository,
)
from src.services.delivery_service import DeliveryService


class FakeDeliveryRepo(DeliveryAttemptRepository):
    def __init__(self) -> None:
        self._items: dict[UUID, DeliveryAttempt] = {}

    async def get_by_id(self, id: UUID) -> DeliveryAttempt | None:
        return self._items.get(id)

    async def get_by_event(
        self, event_id: UUID, cursor: UUID | None, limit: int
    ) -> list[DeliveryAttempt]:
        items = [d for d in self._items.values() if d.event_id == event_id]
        items.sort(key=lambda d: d.id)
        if cursor is not None:
            items = [d for d in items if d.id > cursor]
        return items[:limit]

    async def create(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        self._items[attempt.id] = attempt
        return attempt

    async def update(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        self._items[attempt.id] = attempt
        return attempt

    async def delete(self, id: UUID) -> None:
        self._items.pop(id, None)


class FakeEndpointRepo(EndpointRepository):
    def __init__(self, endpoint: Endpoint) -> None:
        self._endpoint = endpoint

    async def get_by_id(self, id: UUID) -> Endpoint | None:
        return self._endpoint if id == self._endpoint.id else None

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Endpoint]:
        return [self._endpoint] if self._endpoint.owner_id == owner_id else []

    async def create(self, endpoint: Endpoint) -> Endpoint:
        self._endpoint = endpoint
        return endpoint

    async def update(self, endpoint: Endpoint) -> Endpoint:
        self._endpoint = endpoint
        return endpoint

    async def delete(self, id: UUID) -> None:
        return None


@pytest.mark.asyncio
async def test_delivery_history_forbidden() -> None:
    now = datetime.now(UTC)
    endpoint = Endpoint(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="e",
        url="https://example.com",
        owner_id=uuid4(),
        secret=None,
        is_active=True,
        failure_count=0,
    )
    deliveries = FakeDeliveryRepo()
    endpoints = FakeEndpointRepo(endpoint)
    svc = DeliveryService(deliveries, endpoints)

    attempt = DeliveryAttempt(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        event_id=uuid4(),
        endpoint_id=endpoint.id,
        attempt_number=1,
        status=DeliveryStatus.PENDING,
        response_code=None,
        response_body=None,
        error_message=None,
        attempted_at=now,
    )
    await deliveries.create(attempt)

    with pytest.raises(ForbiddenError):
        await svc.get_delivery_history(attempt.event_id, owner_id=uuid4())


@pytest.mark.asyncio
async def test_record_attempt_truncates_body() -> None:
    now = datetime.now(UTC)
    endpoint = Endpoint(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="e",
        url="https://example.com",
        owner_id=uuid4(),
        secret=None,
        is_active=True,
        failure_count=0,
    )
    deliveries = FakeDeliveryRepo()
    svc = DeliveryService(deliveries, FakeEndpointRepo(endpoint))

    created = await svc.create_pending_delivery(
        event_id=uuid4(),
        endpoint_id=endpoint.id,
    )
    long_body = "x" * 5000
    updated = await svc.record_attempt(
        created.id,
        status=DeliveryStatus.FAILED,
        response_code=500,
        response_body=long_body,
    )
    assert updated.response_body is not None
    assert len(updated.response_body) == 1000
