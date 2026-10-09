from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from src.domain.entities.delivery import DeliveryAttempt
from src.domain.entities.subscription import Subscription
from src.domain.entities.webhook_event import WebhookEvent
from src.domain.enums import DeliveryStatus
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.repositories.delivery_attempt_repository import (
    PostgresDeliveryAttemptRepository,
)
from src.infrastructure.queue.delivery_publication import enqueue_delivery

log = structlog.get_logger()


async def dispatch_event_deliveries(
    event: WebhookEvent, subscriptions: list[Subscription]
) -> list[str]:
    """Creates DeliveryAttempt records and dispatches Celery tasks. Returns task IDs."""
    task_ids: list[str] = []
    now = datetime.now(UTC)
    async with async_session_maker() as session:
        repo = PostgresDeliveryAttemptRepository(session)
        for sub in subscriptions:
            if not sub.is_active:
                continue
            attempt = DeliveryAttempt(
                id=uuid4(),
                created_at=now,
                updated_at=now,
                event_id=event.id,
                endpoint_id=sub.endpoint_id,
                attempt_number=1,
                status=DeliveryStatus.PENDING,
                response_code=None,
                response_body=None,
                error_message=None,
                attempted_at=now,
            )
            saved = await repo.create(attempt)
            try:
                task_id = await asyncio.to_thread(
                    enqueue_delivery, str(saved.id), str(event.id), str(sub.endpoint_id)
                )
            except Exception:
                log.warning("delivery_broker_unavailable", delivery_id=str(saved.id))
                continue
            if task_id is not None:
                task_ids.append(task_id)
    return task_ids
