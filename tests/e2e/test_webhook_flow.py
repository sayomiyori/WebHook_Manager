from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import respx
from httpx import Response

from src.domain.entities.endpoint import Endpoint
from src.domain.entities.source import Source
from src.domain.entities.subscription import Subscription
from src.domain.entities.user import User
from src.domain.enums import DeliveryStatus
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
from src.infrastructure.queue.celery_app import celery_app


@pytest.mark.asyncio
async def test_full_delivery_flow(client, db_session) -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
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

    with respx.mock(assert_all_called=False) as respx_mock:
        respx_mock.post("https://receiver.test/hook").mock(
            return_value=Response(200, json={"ok": True})
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
    assert attempts[0].status == DeliveryStatus.SUCCESS

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
async def test_retry_flow(client, db_session) -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
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

    with respx.mock(assert_all_called=False) as respx_mock:
        respx_mock.post("https://receiver.retry/hook").mock(
            return_value=Response(500, json={"error": "boom"})
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
    assert attempts[-1].status == DeliveryStatus.EXHAUSTED

    refreshed = await endpoint_repo.get_by_id(endpoint.id)
    assert refreshed is not None
    assert refreshed.failure_count >= 5

    resp = await client.get(
        "/api/v1/deliveries",
        params={
            "event_id": str(event_id),
            "owner_id": str(user.id),
            "limit": 10,
        },
    )
    assert resp.status_code == 200

