from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.core.exceptions import ForbiddenError, NotFoundError
from src.domain.entities.endpoint import Endpoint
from src.services.endpoint_service import EndpointService


@pytest.mark.asyncio
async def test_create_endpoint() -> None:
    repo = AsyncMock()
    svc = EndpointService(repo)
    owner_id = uuid4()
    created = Endpoint(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="test",
        url="https://example.com",
        owner_id=owner_id,
        secret=None,
        is_active=True,
        failure_count=0,
    )
    repo.create.return_value = created

    out = await svc.create_endpoint(owner_id, "test", "https://example.com", None)
    assert out == created
    repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_own_endpoint() -> None:
    repo = AsyncMock()
    svc = EndpointService(repo)
    owner_id = uuid4()
    endpoint = Endpoint(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="test",
        url="https://example.com",
        owner_id=owner_id,
        secret=None,
        is_active=True,
        failure_count=0,
    )
    repo.get_by_id.return_value = endpoint

    out = await svc.get_endpoint(endpoint.id, owner_id)
    assert out == endpoint


@pytest.mark.asyncio
async def test_get_other_users_endpoint_forbidden() -> None:
    repo = AsyncMock()
    svc = EndpointService(repo)
    endpoint = Endpoint(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="test",
        url="https://example.com",
        owner_id=uuid4(),
        secret=None,
        is_active=True,
        failure_count=0,
    )
    repo.get_by_id.return_value = endpoint

    with pytest.raises(ForbiddenError):
        await svc.get_endpoint(endpoint.id, uuid4())


@pytest.mark.asyncio
async def test_delete_nonexistent_raises_not_found() -> None:
    repo = AsyncMock()
    svc = EndpointService(repo)
    repo.get_by_id.return_value = None

    with pytest.raises(NotFoundError):
        await svc.delete_endpoint(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_increment_failure_count() -> None:
    repo = AsyncMock()
    endpoint = Endpoint(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="test",
        url="https://example.com",
        owner_id=uuid4(),
        secret=None,
        is_active=True,
        failure_count=2,
    )
    repo.get_by_id.return_value = endpoint
    repo.update.return_value = endpoint
    svc = EndpointService(repo)
    out = await svc.increment_failure(endpoint.id)
    assert out.failure_count == 3
    repo.update.assert_awaited_once()
