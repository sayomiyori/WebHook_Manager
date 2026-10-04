"""Exercise the built API and real worker using a controlled local receiver.

Requires docs/verification.compose.yml API/worker and dedicated PostgreSQL/Redis.
Credentials are test-only, kept in process memory and never printed.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx

from src.core.security import hmac_sha256_hex
from src.domain.entities.source import Source
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.repositories.api_key_repository import (
    PostgresApiKeyRepository,
)
from src.infrastructure.db.repositories.source_repository import (
    PostgresSourceRepository,
)
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository
from src.services.auth_service import AuthService

RECEIVED = []


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        RECEIVED.append((self.path, body, dict(self.headers)))
        self.send_response(500 if self.path == "/fail" else 200)
        self.end_headers()
        self.wfile.write(b"controlled receiver")

    def log_message(self, *_):
        pass


async def provision(user_id):
    async with async_session_maker() as session:
        auth = AuthService(
            PostgresApiKeyRepository(session), PostgresUserRepository(session)
        )
        _, key = await auth.create_api_key(user_id, "local-smoke")
        now = datetime.now(UTC)
        source = await PostgresSourceRepository(session).create(
            Source(
                id=uuid4(),
                created_at=now,
                updated_at=now,
                name="local smoke",
                slug=str(uuid4()),
                owner_id=user_id,
                secret="local-signing-only",
                is_active=True,
            )
        )
        return key, source


def main():
    from uuid import UUID

    server = ThreadingHTTPServer(("0.0.0.0", 38181), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url="http://127.0.0.1:38081", timeout=10) as api:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    response = api.get("/health/ready")
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.2)
            else:
                raise AssertionError("API did not become ready")
            email = f"http-{uuid4()}@example.com"
            response = api.post(
                "/api/v1/auth/register",
                json={"email": email, "password": "local-smoke-only"},
            )
            assert response.status_code == 201, response.status_code
            user_id = UUID(response.json()["user_id"])
            assert (
                api.post(
                    "/api/v1/auth/login", json={"email": email, "password": "wrong"}
                ).status_code
                == 401
            )
            assert (
                api.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": "local-smoke-only"},
                ).status_code
                == 200
            )
            key, source = asyncio.run(provision(user_id))
            assert (
                api.get(
                    "/api/v1/endpoints", params={"owner_id": str(user_id)}
                ).status_code
                == 401
            )
            api.headers["X-API-Key"] = key
            assert (
                api.get(
                    "/api/v1/endpoints", params={"owner_id": str(uuid4())}
                ).status_code
                == 403
            )
            payload = json.dumps({"verification": True}, separators=(",", ":")).encode()
            signature = "sha256=" + hmac_sha256_hex(
                secret="local-signing-only", message=payload
            )
            headers = {
                "X-Webhook-Signature": signature,
                "X-Idempotency-Key": str(uuid4()),
                "X-Event-Type": "smoke",
            }
            for path, expected in [("/ok", "success"), ("/fail", "exhausted")]:
                endpoint = api.post(
                    "/api/v1/endpoints",
                    json={
                        "name": path,
                        "url": "http://host.docker.internal:38181" + path,
                        "secret": "local-signing-only",
                    },
                )
                assert endpoint.status_code == 201
                subscription = api.post(
                    "/api/v1/subscriptions",
                    json={
                        "owner_id": str(user_id),
                        "source_id": str(source.id),
                        "endpoint_id": endpoint.json()["id"],
                        "event_type_filter": ["smoke" + path],
                    },
                )
                assert subscription.status_code == 201
                headers["X-Idempotency-Key"] = str(uuid4())
                headers["X-Event-Type"] = "smoke" + path
                url = "/webhooks/ingest/" + source.slug
                assert api.post(url, content=payload).status_code == 401
                event = api.post(url, content=payload, headers=headers)
                assert event.status_code == 202
                duplicate = api.post(url, content=payload, headers=headers)
                assert duplicate.status_code == 200
                assert duplicate.json()["event_id"] == event.json()["event_id"]
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    history = api.get(
                        "/api/v1/deliveries",
                        params={
                            "event_id": event.json()["event_id"],
                            "owner_id": str(user_id),
                        },
                    )
                    assert history.status_code == 200
                    if (
                        history.json()["items"]
                        and history.json()["items"][0]["status"] == expected
                    ):
                        break
                    time.sleep(0.2)
                else:
                    raise AssertionError("Worker did not reach " + expected)
                received = [item for item in RECEIVED if item[0] == path]
                assert len(received) == 1
                assert received[0][1] == payload
                assert not any(
                    name.lower() in {"authorization", "x-api-key", "cookie"}
                    for name in received[0][2]
                )
                assert received[0][2]["X-Webhook-Signature"] == signature
            assert api.get("/metrics").status_code == 200
            assert (
                api.delete(
                    "/api/v1/auth/keys/" + api.get("/api/v1/auth/keys").json()[0]["id"]
                ).status_code
                == 204
            )
            assert (
                api.get(
                    "/api/v1/endpoints", params={"owner_id": str(user_id)}
                ).status_code
                == 401
            )
            print(
                "PASS: readiness, register/login, API key, ownership, HMAC, duplicate, "
                "real queue delivery, receiver 500, revocation, metrics"
            )
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
