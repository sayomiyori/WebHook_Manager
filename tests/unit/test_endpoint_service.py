from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.core.exceptions import ForbiddenError, NotFoundError
from src.domain.entities.endpoint import Endpoint
from src.domain.interfaces.repositories import EndpointRepository
from src.services.endpoint_service import EndpointService


class FakeEndpointRepo(EndpointRepository):
    def __init__(self) -> None:
        self._items: dict[UUID, Endpoint] = {}

    async def get_by_id(self, id: UUID) -> Endpoint | None:
        return self._items.get(id)

    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Endpoint]:
        items = [e for e in self._items.values() if e.owner_id == owner_id]
        items.sort(key=lambda e: e.id)
        if cursor is not None:
            items = [e for e in items if e.id > cursor]
        return items[:limit]

    async def create(self, endpoint: Endpoint) -> Endpoint:
        self._items[endpoint.id] = endpoint
        return endpoint

    async def update(self, endpoint: Endpoint) -> Endpoint:
        self._items[endpoint.id] = endpoint
        return endpoint

    async def delete(self, id: UUID) -> None:
        self._items.pop(id, None)


@pytest.mark.asyncio
async def test_get_endpoint_not_found() -> None:
    svc = EndpointService(FakeEndpointRepo())
    with pytest.raises(NotFoundError):
        await svc.get_endpoint(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_get_endpoint_forbidden() -> None:
    repo = FakeEndpointRepo()
    owner_id = uuid4()
    other_owner = uuid4()
    now = datetime.now(UTC)
    endpoint = Endpoint(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="e",
        url="https://example.com",
        owner_id=owner_id,
        secret=None,
        is_active=True,
        failure_count=0,
    )
    await repo.create(endpoint)

    svc = EndpointService(repo)
    with pytest.raises(ForbiddenError):
        await svc.get_endpoint(endpoint.id, other_owner)


@pytest.mark.asyncio
async def test_increment_and_reset_failure() -> None:
    repo = FakeEndpointRepo()
    owner_id = uuid4()
    now = datetime.now(UTC)
    endpoint = Endpoint(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="e",
        url="https://example.com",
        owner_id=owner_id,
        secret=None,
        is_active=True,
        failure_count=0,
    )
    await repo.create(endpoint)
    svc = EndpointService(repo)

    updated = await svc.increment_failure(endpoint.id)
    assert updated.failure_count == 1

    await svc.reset_failure_count(endpoint.id)
    reread = await repo.get_by_id(endpoint.id)
    assert reread is not None
    assert reread.failure_count == 0


@pytest.mark.asyncio
async def test_list_endpoints_next_cursor() -> None:
    repo = FakeEndpointRepo()
    owner_id = uuid4()
    now = datetime.now(UTC)
    e1 = Endpoint(
        id=UUID(int=1),
        created_at=now,
        updated_at=now,
        name="1",
        url="https://example.com/1",
        owner_id=owner_id,
        secret=None,
        is_active=True,
        failure_count=0,
    )
    e2 = Endpoint(
        id=UUID(int=2),
        created_at=now,
        updated_at=now,
        name="2",
        url="https://example.com/2",
        owner_id=owner_id,
        secret=None,
        is_active=True,
        failure_count=0,
    )
    await repo.create(e1)
    await repo.create(e2)

    svc = EndpointService(repo)
    items, next_cursor = await svc.list_endpoints(owner_id, cursor=None, limit=1)
    assert [e.id for e in items] == [UUID(int=1)]
    assert next_cursor == UUID(int=1)
