from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from src.domain.entities.endpoint import Endpoint
from src.domain.entities.source import Source
from src.domain.entities.subscription import Subscription
from src.domain.entities.user import User
from src.domain.enums import DeliveryStatus
from src.infrastructure.db.repositories.api_key_repository import (
    PostgresApiKeyRepository,
)
from src.infrastructure.db.repositories.delivery_attempt_repository import (
    PostgresDeliveryAttemptRepository,
)
from src.infrastructure.db.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from src.infrastructure.db.repositories.source_repository import (
    PostgresSourceRepository,
)
from src.infrastructure.db.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository
from src.infrastructure.queue import dispatcher
from src.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_full_delivery_flow(client, db_session, monkeypatch) -> None:
    queued = Mock(return_value="queued-test-task")
    monkeypatch.setattr(dispatcher, "enqueue_delivery", queued)
    now = datetime.now(UTC)

    user = await PostgresUserRepository(db_session).create(
        User(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            email=f"e2e-{uuid4()}@example.com",
            hashed_password="x",
            is_active=True,
        )
    )
    source = await PostgresSourceRepository(db_session).create(
        Source(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="Test Source",
            slug="test-source",
            owner_id=user.id,
            secret=None,
            is_active=True,
        )
    )
    endpoint = await PostgresEndpointRepository(db_session).create(
        Endpoint(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="Test Endpoint",
            url="https://receiver.test/hook",
            owner_id=user.id,
            secret=None,
            is_active=True,
            failure_count=0,
        )
    )
    await PostgresSubscriptionRepository(db_session).create(
        Subscription(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            endpoint_id=endpoint.id,
            source_id=source.id,
            owner_id=user.id,
            event_type_filter=["payment.*"],
            is_active=True,
        )
    )

    resp = await client.post(
        "/webhooks/ingest/test-source",
        headers={"X-Event-Type": "payment.created"},
        json={"hello": "world"},
    )
    assert resp.status_code == 202
    event_id = UUID(resp.json()["event_id"])

    attempts = await PostgresDeliveryAttemptRepository(db_session).get_by_event(
        event_id=event_id,
        cursor=None,
        limit=100,
    )
    assert attempts
    assert attempts[0].status == DeliveryStatus.PENDING
    queued.assert_called_once_with(str(attempts[0].id), str(event_id), str(endpoint.id))
    _, key = await AuthService(
        PostgresApiKeyRepository(db_session), PostgresUserRepository(db_session)
    ).create_api_key(user.id, "test")
    client.headers.update({"X-API-Key": key})

    # Deliveries API (covers deliveries router and ownership checks)
    resp = await client.get(
        "/api/v1/deliveries",
        params={"event_id": str(event_id), "owner_id": str(user.id), "limit": 10},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) >= 1

    resp = await client.get(
        "/api/v1/deliveries",
        params={
            "event_id": str(event_id),
            "owner_id": str(uuid4()),
            "limit": 10,
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dispatch_persists_pending_delivery(
    client, db_session, monkeypatch
) -> None:
    queued = Mock(return_value="queued-test-task")
    monkeypatch.setattr(dispatcher, "enqueue_delivery", queued)
    now = datetime.now(UTC)

    user = await PostgresUserRepository(db_session).create(
        User(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            email=f"e2e-r-{uuid4()}@example.com",
            hashed_password="x",
            is_active=True,
        )
    )
    source = await PostgresSourceRepository(db_session).create(
        Source(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="Retry Source",
            slug="retry-source",
            owner_id=user.id,
            secret=None,
            is_active=True,
        )
    )
    endpoint_repo = PostgresEndpointRepository(db_session)
    endpoint = await endpoint_repo.create(
        Endpoint(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="Retry Endpoint",
            url="https://receiver.retry/hook",
            owner_id=user.id,
            secret=None,
            is_active=True,
            failure_count=0,
        )
    )
    await PostgresSubscriptionRepository(db_session).create(
        Subscription(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            endpoint_id=endpoint.id,
            source_id=source.id,
            owner_id=user.id,
            event_type_filter=["*"],
            is_active=True,
        )
    )

    resp = await client.post(
        "/webhooks/ingest/retry-source",
        headers={"X-Event-Type": "order.created"},
        json={"hello": "world"},
    )
    assert resp.status_code == 202
    event_id = UUID(resp.json()["event_id"])

    attempts = await PostgresDeliveryAttemptRepository(db_session).get_by_event(
        event_id=event_id,
        cursor=None,
        limit=100,
    )
    assert attempts
    assert attempts[-1].status == DeliveryStatus.PENDING
    queued.assert_called_once()
    _, key = await AuthService(
        PostgresApiKeyRepository(db_session), PostgresUserRepository(db_session)
    ).create_api_key(user.id, "test")
    client.headers.update({"X-API-Key": key})

    refreshed = await endpoint_repo.get_by_id(endpoint.id)
    assert refreshed is not None
    assert refreshed.failure_count == 0

    resp = await client.get(
        "/api/v1/deliveries",
        params={
            "event_id": str(event_id),
            "owner_id": str(user.id),
            "limit": 10,
        },
    )
    assert resp.status_code == 200
