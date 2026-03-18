from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from src.core.config import settings
from src.core.constants import DELIVERY_RETRY_DELAYS_SECONDS
from src.core.security import hmac_sha256_hex
from src.domain.entities.delivery import DeliveryAttempt
from src.domain.enums import DeliveryStatus
from src.infrastructure.cache.redis_client import get_redis
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.repositories.delivery_attempt_repository import (
    PostgresDeliveryAttemptRepository,
)
from src.infrastructure.db.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from src.infrastructure.db.repositories.webhook_event_repository import (
    PostgresWebhookEventRepository,
)
from src.infrastructure.queue.celery_app import celery
from src.infrastructure.queue.tasks.circuit_breaker import CircuitBreaker


async def _run(attempt_id: UUID) -> None:
    async with async_session_maker() as session:
        attempts = PostgresDeliveryAttemptRepository(session)
        endpoints = PostgresEndpointRepository(session)
        events = PostgresWebhookEventRepository(session)
        breaker = CircuitBreaker(get_redis())

        attempt = await attempts.get_by_id(attempt_id)
        if attempt is None:
            return

        endpoint = await endpoints.get_by_id(attempt.endpoint_id)
        event = await events.get_by_id(attempt.event_id)
        if endpoint is None or event is None:
            attempt.status = DeliveryStatus.FAILED
            attempt.error_message = "Missing endpoint or event"
            attempt.updated_at = datetime.now(UTC)
            await attempts.update(attempt)
            return

        attempt.status = DeliveryStatus.DELIVERING
        attempt.attempted_at = datetime.now(UTC)
        attempt.updated_at = attempt.attempted_at
        await attempts.update(attempt)

        payload_bytes = json.dumps(
            event.payload, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        headers = dict(event.headers)
        headers.setdefault("Content-Type", "application/json")
        headers["X-Webhook-Event-Id"] = str(event.id)
        if endpoint.secret:
            headers["X-Webhook-Signature"] = hmac_sha256_hex(
                secret=endpoint.secret,
                message=payload_bytes,
            )

        try:
            async with httpx.AsyncClient(
                timeout=settings.DELIVERY_TIMEOUT_SECONDS
            ) as client:
                resp = await client.post(
                    endpoint.url,
                    content=payload_bytes,
                    headers=headers,
                )
            attempt.response_code = resp.status_code
            body_text = resp.text
            attempt.response_body = body_text[:1000] if body_text else None

            if 200 <= resp.status_code < 300:
                attempt.status = DeliveryStatus.SUCCESS
                attempt.error_message = None
                attempt.updated_at = datetime.now(UTC)
                await attempts.update(attempt)
                await breaker.reset(endpoint_id=str(endpoint.id))
                return

            attempt.status = DeliveryStatus.FAILED
            attempt.error_message = f"Non-2xx response: {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            attempt.status = DeliveryStatus.FAILED
            attempt.error_message = str(exc)

        attempt.updated_at = datetime.now(UTC)
        await attempts.update(attempt)

        await breaker.record_failure(endpoint_id=str(endpoint.id))
        if attempt.attempt_number >= settings.MAX_DELIVERY_ATTEMPTS:
            attempt.status = DeliveryStatus.EXHAUSTED
            attempt.updated_at = datetime.now(UTC)
            await attempts.update(attempt)
            return

        delay = DELIVERY_RETRY_DELAYS_SECONDS[
            min(attempt.attempt_number - 1, len(DELIVERY_RETRY_DELAYS_SECONDS) - 1)
        ]
        now = datetime.now(UTC)
        next_attempt = DeliveryAttempt(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            event_id=attempt.event_id,
            endpoint_id=attempt.endpoint_id,
            attempt_number=attempt.attempt_number + 1,
            status=DeliveryStatus.RETRYING,
            response_code=None,
            response_body=None,
            error_message=None,
            attempted_at=now,
        )
        saved = await attempts.create(next_attempt)
        celery.send_task(
            "src.infrastructure.queue.tasks.deliver_webhook.deliver_webhook",
            args=(str(saved.id),),
            countdown=delay,
        )


@celery.task(  # type: ignore[untyped-decorator]
    name="src.infrastructure.queue.tasks.deliver_webhook.deliver_webhook"
)
def deliver_webhook(attempt_id: str) -> None:
    asyncio.run(_run(UUID(attempt_id)))

