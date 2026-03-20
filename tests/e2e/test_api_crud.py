from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.domain.entities.source import Source
from src.domain.entities.user import User
from src.infrastructure.db.repositories.source_repository import (
    PostgresSourceRepository,
)


@pytest.mark.asyncio
async def test_auth_endpoints_and_crud_flow(
    client,
    db_session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    # Health + metrics
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = await client.get("/health/live")
    assert r.status_code == 200

    r = await client.get("/health/ready")
    assert r.status_code == 200

    r = await client.get("/metrics")
    assert r.status_code == 200

    # Auth: register + login invalid/valid
    email = f"api-{uuid4()}@example.com"
    password = "secret123"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert r.status_code == 201
    user_id = UUID(r.json()["user_id"])

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert r.status_code == 401

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200
    assert UUID(r.json()["user_id"]) == user_id

    # Auth: keys create/list/delete (protected)
    r = await client.post(
        "/api/v1/auth/keys",
        json={"owner_id": str(test_user.id), "name": "k2"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    created_key_id = r.json()["id"]

    r = await client.get("/api/v1/auth/keys", headers=auth_headers)
    assert r.status_code == 200
    keys = r.json()
    assert any(k["id"] == created_key_id for k in keys)

    r = await client.delete(f"/api/v1/auth/keys/{created_key_id}", headers=auth_headers)
    assert r.status_code == 204

    # Create a source for subscriptions/events
    now = datetime.now(UTC)
    source = await PostgresSourceRepository(db_session).create(
        Source(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="CRUD Source",
            slug="crud-source",
            owner_id=test_user.id,
            secret=None,
            is_active=True,
        )
    )

    # Endpoint CRUD
    r = await client.post(
        "/api/v1/endpoints",
        json={
            "owner_id": str(test_user.id),
            "name": "ep",
            "url": "https://receiver.test/ep",
            "secret": "s1",
            "is_active": True,
        },
    )
    assert r.status_code == 201
    endpoint_id = UUID(r.json()["id"])

    r = await client.get(
        f"/api/v1/endpoints/{endpoint_id}",
        params={"owner_id": str(test_user.id)},
    )
    assert r.status_code == 200

    r = await client.get(
        f"/api/v1/endpoints/{endpoint_id}",
        params={"owner_id": str(uuid4())},
    )
    assert r.status_code == 403

    r = await client.get(
        "/api/v1/endpoints",
        params={"owner_id": str(test_user.id), "limit": 1},
    )
    assert r.status_code == 200
    assert "items" in r.json()

    r = await client.put(
        f"/api/v1/endpoints/{endpoint_id}",
        params={"owner_id": str(test_user.id)},
        json={"secret": "s2", "is_active": False},
    )
    assert r.status_code == 200
    assert r.json()["secret"] == "s2"
    assert r.json()["is_active"] is False

    # Subscriptions CRUD
    r = await client.post(
        "/api/v1/subscriptions",
        json={
            "owner_id": str(test_user.id),
            "endpoint_id": str(endpoint_id),
            "source_id": str(source.id),
            "event_type_filter": ["payment.*"],
            "is_active": True,
        },
    )
    assert r.status_code == 201
    subscription_id = UUID(r.json()["id"])

    r = await client.get(
        f"/api/v1/subscriptions/{subscription_id}",
        params={"owner_id": str(test_user.id)},
    )
    assert r.status_code == 200

    r = await client.get(
        "/api/v1/subscriptions",
        params={"owner_id": str(test_user.id), "limit": 1},
    )
    assert r.status_code == 200

    r = await client.put(
        f"/api/v1/subscriptions/{subscription_id}",
        json={"event_type_filter": ["order.*"], "is_active": False},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = await client.delete(f"/api/v1/subscriptions/{subscription_id}")
    assert r.status_code == 204

    # Events CRUD
    r = await client.post(
        "/api/v1/events",
        json={
            "source_id": str(source.id),
            "payload": {"hello": "world"},
            "idempotency_key": None,
            "event_type": "payment.created",
            "headers": {"X-Test": "1"},
        },
    )
    assert r.status_code == 201
    event_id = UUID(r.json()["id"])

    r = await client.get(f"/api/v1/events/{event_id}")
    assert r.status_code == 200

    r = await client.get(
        "/api/v1/events",
        params={"source_id": str(source.id), "limit": 10},
    )
    assert r.status_code == 200

    # Endpoint delete + not found path
    r = await client.delete(
        f"/api/v1/endpoints/{endpoint_id}",
        params={"owner_id": str(test_user.id)},
    )
    assert r.status_code == 204

    r = await client.delete(
        f"/api/v1/endpoints/{endpoint_id}",
        params={"owner_id": str(test_user.id)},
    )
    assert r.status_code == 404

