from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.endpoint import Endpoint
from src.domain.entities.user import User
from src.infrastructure.db.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository


@pytest.mark.asyncio
async def test_endpoint_repository_crud(db_session) -> None:
    user_repo = PostgresUserRepository(db_session)
    endpoint_repo = PostgresEndpointRepository(db_session)
    now = datetime.now(UTC)
    user = await user_repo.create(
        User(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            email=f"repo-{uuid4()}@example.com",
            hashed_password="x",
            is_active=True,
        )
    )

    endpoint = Endpoint(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="e1",
        url="https://example.com/hook",
        owner_id=user.id,
        secret=None,
        is_active=True,
        failure_count=0,
    )
    created = await endpoint_repo.create(endpoint)
    fetched = await endpoint_repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.name == "e1"

    fetched.name = "e2"
    updated = await endpoint_repo.update(fetched)
    assert updated.name == "e2"

    await endpoint_repo.delete(updated.id)
    assert await endpoint_repo.get_by_id(updated.id) is None


@pytest.mark.asyncio
async def test_endpoint_repository_pagination(db_session) -> None:
    user_repo = PostgresUserRepository(db_session)
    endpoint_repo = PostgresEndpointRepository(db_session)
    now = datetime.now(UTC)
    user = await user_repo.create(
        User(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            email=f"repo-page-{uuid4()}@example.com",
            hashed_password="x",
            is_active=True,
        )
    )

    for i in range(15):
        await endpoint_repo.create(
            Endpoint(
                id=uuid4(),
                created_at=now,
                updated_at=now,
                name=f"e{i}",
                url=f"https://example.com/{i}",
                owner_id=user.id,
                secret=None,
                is_active=True,
                failure_count=0,
            )
        )

    page1 = await endpoint_repo.get_by_owner(user.id, cursor=None, limit=10)
    assert len(page1) == 10
    cursor = page1[-1].id
    page2 = await endpoint_repo.get_by_owner(user.id, cursor=cursor, limit=10)
    assert len(page2) == 5

