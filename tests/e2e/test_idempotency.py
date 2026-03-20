from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.domain.entities.source import Source
from src.domain.entities.user import User
from src.infrastructure.db.repositories.source_repository import (
    PostgresSourceRepository,
)
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository
from src.infrastructure.db.repositories.webhook_event_repository import (
    PostgresWebhookEventRepository,
)


@pytest.mark.asyncio
async def test_ingest_idempotency_same_key_same_event(client, db_session) -> None:
    now = datetime.now(UTC)
    user = await PostgresUserRepository(db_session).create(
        User(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            email=f"idem-{uuid4()}@example.com",
            hashed_password="x",
            is_active=True,
        )
    )
    source = await PostgresSourceRepository(db_session).create(
        Source(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="Idem Source",
            slug="idem-source",
            owner_id=user.id,
            secret=None,
            is_active=True,
        )
    )

    headers = {"X-Idempotency-Key": "test-123", "X-Event-Type": "payment.created"}
    r1 = await client.post(
        "/webhooks/ingest/idem-source",
        headers=headers,
        json={"a": 1},
    )
    r2 = await client.post(
        "/webhooks/ingest/idem-source",
        headers=headers,
        json={"a": 1},
    )
    assert r1.status_code == 202
    assert r2.status_code == 200
    event_id_1 = UUID(r1.json()["event_id"])
    event_id_2 = UUID(r2.json()["event_id"])
    assert event_id_1 == event_id_2

    events = await PostgresWebhookEventRepository(db_session).get_by_source(
        source.id, cursor=None, limit=100
    )
    assert len(events) == 1

