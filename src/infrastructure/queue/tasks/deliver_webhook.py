from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import structlog
from celery.exceptions import MaxRetriesExceededError  # type: ignore[import-untyped]

from src.core.config import settings
from src.core.security import hmac_sha256_hex
from src.domain.enums import DeliveryStatus
from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.models.delivery_attempt import DeliveryAttemptModel
from src.infrastructure.db.models.endpoint import EndpointModel
from src.infrastructure.db.models.webhook_event import WebhookEventModel
from src.infrastructure.queue.backoff import get_backoff_delay
from src.infrastructure.queue.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="deliver_webhook",
    max_retries=5,
    soft_time_limit=15,
    time_limit=20,
)
def deliver_webhook(
    self: Any, delivery_id: str, event_id: str, endpoint_id: str
) -> dict[str, int | str | None]:
    delivery_uuid = UUID(delivery_id)
    event_uuid = UUID(event_id)
    endpoint_uuid = UUID(endpoint_id)

    with sync_session_maker() as session:
        delivery = session.get(DeliveryAttemptModel, delivery_uuid)
        if delivery is None:
            return {"status": "failed", "response_code": None}

        # Idempotency: already finalized attempts are safe to return.
        if delivery.status in (DeliveryStatus.SUCCESS, DeliveryStatus.EXHAUSTED):
            return {
                "status": str(delivery.status),
                "response_code": delivery.response_code,
            }

        event = session.get(WebhookEventModel, event_uuid)
        endpoint = session.get(EndpointModel, endpoint_uuid)
        if (
            event is None
            or endpoint is None
            or delivery.event_id != event.id
            or delivery.endpoint_id != endpoint.id
        ):
            delivery.status = DeliveryStatus.EXHAUSTED
            delivery.error_message = "Inconsistent delivery/event/endpoint reference"
            delivery.updated_at = datetime.now(UTC)
            session.commit()
            return {"status": "failed", "response_code": None}

        # Circuit breaker: short-circuit very unhealthy endpoint.
        if endpoint.failure_count >= 10:
            delivery.status = DeliveryStatus.EXHAUSTED
            delivery.error_message = "Circuit breaker open"
            delivery.updated_at = datetime.now(UTC)
            session.commit()
            return {"status": "failed", "response_code": None}

        delivery.status = DeliveryStatus.DELIVERING
        delivery.attempted_at = datetime.now(UTC)
        delivery.updated_at = delivery.attempted_at
        session.commit()

        payload_text = json.dumps(
            event.payload,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        payload_bytes = payload_text.encode("utf-8")
        headers: dict[str, str] = dict(event.headers)
        headers.setdefault("Content-Type", "application/json")
        headers["X-Webhook-ID"] = str(event.id)
        if endpoint.secret:
            signature = hmac_sha256_hex(
                secret=endpoint.secret,
                message=payload_bytes,
            )
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        started = time.perf_counter()
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    endpoint.url,
                    content=payload_bytes,
                    headers=headers,
                )
            duration_ms = int((time.perf_counter() - started) * 1000)
            delivery.response_code = resp.status_code
            body_text = resp.text
            delivery.response_body = body_text[:1000] if body_text else None

            if 200 <= resp.status_code < 300:
                delivery.status = DeliveryStatus.SUCCESS
                delivery.error_message = None
                delivery.updated_at = datetime.now(UTC)
                endpoint.failure_count = 0
                endpoint.updated_at = delivery.updated_at
                session.commit()
                log.info(
                    "delivery_attempt",
                    delivery_id=delivery_id,
                    endpoint_url=endpoint.url,
                    attempt_number=delivery.attempt_number,
                    response_code=resp.status_code,
                    duration_ms=duration_ms,
                )
                return {"status": "success", "response_code": resp.status_code}

            # Non-2xx counts as failure.
            raise RuntimeError(f"Non-2xx response: {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started) * 1000)
            endpoint.failure_count += 1
            endpoint.updated_at = datetime.now(UTC)
            delivery.status = DeliveryStatus.FAILED
            delivery.error_message = str(exc)
            delivery.updated_at = endpoint.updated_at
            session.commit()
            log.info(
                "delivery_attempt",
                delivery_id=delivery_id,
                endpoint_url=endpoint.url,
                attempt_number=delivery.attempt_number,
                response_code=delivery.response_code,
                duration_ms=duration_ms,
            )

            if delivery.attempt_number >= settings.MAX_DELIVERY_ATTEMPTS:
                delivery.status = DeliveryStatus.EXHAUSTED
                delivery.updated_at = datetime.now(UTC)
                session.commit()
                return {"status": "failed", "response_code": delivery.response_code}

            delay = get_backoff_delay(max(delivery.attempt_number - 1, 0))
            try:
                raise self.retry(countdown=delay, exc=exc)
            except MaxRetriesExceededError:
                delivery.status = DeliveryStatus.EXHAUSTED
                delivery.updated_at = datetime.now(UTC)
                session.commit()
                return {"status": "failed", "response_code": delivery.response_code}

