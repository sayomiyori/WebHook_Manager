from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.source import Source
from src.infrastructure.db.repositories.source_repository import (
    PostgresSourceRepository,
)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/v1/endpoints", None),
        ("GET", "/api/v1/events", None),
        ("GET", "/api/v1/subscriptions", None),
        ("GET", "/api/v1/deliveries", None),
        (
            "POST",
            "/api/v1/events",
            {"source_id": str(uuid4()), "payload": {}, "headers": {}},
        ),
        (
            "POST",
            "/api/v1/deliveries",
            {"event_id": str(uuid4()), "endpoint_id": str(uuid4())},
        ),
    ],
)
async def test_management_requires_authentication(client, method, path, body):
    response = await client.request(method, path, json=body)
    assert response.status_code == 401


async def test_other_user_cannot_access_or_link_resources(
    client, db_session, test_user, auth_headers
):
    from src.infrastructure.db.repositories.api_key_repository import (
        PostgresApiKeyRepository,
    )
    from src.infrastructure.db.repositories.user_repository import (
        PostgresUserRepository,
    )
    from src.services.auth_service import AuthService

    client.headers.update(auth_headers)
    now = datetime.now(UTC)
    source = await PostgresSourceRepository(db_session).create(
        Source(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="owner-source",
            slug=str(uuid4()),
            owner_id=test_user.id,
            secret="test-only-signing",
            is_active=True,
        )
    )
    endpoint = (
        await client.post(
            "/api/v1/endpoints",
            json={
                "name": "owned",
                "url": "https://receiver.test/hook",
                "secret": "private-test-only",
            },
        )
    ).json()
    subscription = (
        await client.post(
            "/api/v1/subscriptions",
            json={
                "owner_id": str(test_user.id),
                "source_id": str(source.id),
                "endpoint_id": endpoint["id"],
            },
        )
    ).json()
    event = (
        await client.post(
            "/api/v1/events",
            json={
                "source_id": str(source.id),
                "payload": {"private": True},
                "headers": {},
            },
        )
    ).json()
    delivery = (
        await client.post(
            "/api/v1/deliveries",
            json={"event_id": event["id"], "endpoint_id": endpoint["id"]},
        )
    ).json()
    auth = AuthService(
        PostgresApiKeyRepository(db_session), PostgresUserRepository(db_session)
    )
    other = await auth.register_user(
        f"other-{uuid4()}@example.com", "test-only-password"
    )
    _, key = await auth.create_api_key(other.id, "other")
    client.headers.update({"X-API-Key": key})
    requests = [
        (
            "GET",
            f"/api/v1/endpoints/{endpoint['id']}",
            {"owner_id": str(test_user.id)},
            None,
        ),
        ("GET", "/api/v1/endpoints", {"owner_id": str(test_user.id)}, None),
        (
            "PUT",
            f"/api/v1/endpoints/{endpoint['id']}",
            {"owner_id": str(test_user.id)},
            {"name": "stolen"},
        ),
        (
            "DELETE",
            f"/api/v1/endpoints/{endpoint['id']}",
            {"owner_id": str(test_user.id)},
            None,
        ),
        ("GET", f"/api/v1/events/{event['id']}", {}, None),
        ("GET", "/api/v1/events", {"source_id": str(source.id)}, None),
        (
            "POST",
            "/api/v1/events",
            {},
            {"source_id": str(source.id), "payload": {}, "headers": {}},
        ),
        ("GET", f"/api/v1/subscriptions/{subscription['id']}", {}, None),
        ("GET", "/api/v1/subscriptions", {"owner_id": str(test_user.id)}, None),
        (
            "PUT",
            f"/api/v1/subscriptions/{subscription['id']}",
            {},
            {"is_active": False},
        ),
        ("DELETE", f"/api/v1/subscriptions/{subscription['id']}", {}, None),
        (
            "POST",
            "/api/v1/subscriptions",
            {},
            {
                "owner_id": str(other.id),
                "source_id": str(source.id),
                "endpoint_id": endpoint["id"],
            },
        ),
        (
            "GET",
            "/api/v1/deliveries",
            {"owner_id": str(test_user.id), "event_id": event["id"]},
            None,
        ),
        (
            "POST",
            "/api/v1/deliveries",
            {},
            {"event_id": event["id"], "endpoint_id": endpoint["id"]},
        ),
        ("POST", f"/api/v1/deliveries/{delivery['id']}/retry", {}, None),
    ]
    for method, path, params, body in requests:
        response = await client.request(method, path, params=params, json=body)
        assert response.status_code == 403, (method, path, response.status_code)


async def test_ingest_signature_validation_and_payload_failures(
    client, db_session, test_user
):
    from src.core.security import hmac_sha256_hex

    now = datetime.now(UTC)
    secret = "test-only-signing"
    slug = str(uuid4())
    await PostgresSourceRepository(db_session).create(
        Source(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name="signed",
            slug=slug,
            owner_id=test_user.id,
            secret=secret,
            is_active=True,
        )
    )
    url = f"/webhooks/ingest/{slug}"
    assert (await client.post(url, json={})).status_code == 401
    for payload, expected in [(b'{"a":1}', 202), (b"[]", 400), (b"invalid", 400)]:
        headers = {
            "X-Webhook-Signature": "sha256="
            + hmac_sha256_hex(secret=secret, message=payload)
        }
        assert (
            await client.post(url, content=payload, headers=headers)
        ).status_code == expected
    assert (await client.post(url, content=b"a" * 1_048_577)).status_code == 413
    assert (await client.post("/webhooks/ingest/missing", json={})).status_code == 404


async def test_public_ingest_rejects_ambiguous_owner_scoped_slug(
    client, db_session, test_user
):
    from src.infrastructure.db.repositories.api_key_repository import (
        PostgresApiKeyRepository,
    )
    from src.infrastructure.db.repositories.user_repository import (
        PostgresUserRepository,
    )
    from src.services.auth_service import AuthService

    other = await AuthService(
        PostgresApiKeyRepository(db_session), PostgresUserRepository(db_session)
    ).register_user(f"slug-{uuid4()}@example.com", "test-only")
    now = datetime.now(UTC)
    slug = str(uuid4())
    repo = PostgresSourceRepository(db_session)
    for owner in [test_user, other]:
        await repo.create(
            Source(
                id=uuid4(),
                created_at=now,
                updated_at=now,
                name="ambiguous",
                slug=slug,
                owner_id=owner.id,
                secret=None,
                is_active=True,
            )
        )
    assert (await client.post(f"/webhooks/ingest/{slug}", json={})).status_code == 404
