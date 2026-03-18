from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from src.core.constants import DELIVERY_RETRY_DELAYS_SECONDS
from src.core.exceptions import ForbiddenError, NotFoundError
from src.domain.entities.delivery import DeliveryAttempt
from src.domain.enums import DeliveryStatus
from src.domain.interfaces.repositories import (
    DeliveryRepository,
    EndpointRepository,
)


class DeliveryService:
    def __init__(
        self,
        delivery_repo: DeliveryRepository,
        endpoint_repo: EndpointRepository,
    ) -> None:
        self._deliveries = delivery_repo
        self._endpoints = endpoint_repo

    async def get_delivery(self, delivery_id: UUID) -> DeliveryAttempt | None:
        return await self._deliveries.get_by_id(delivery_id)

    async def get_delivery_history(
        self, event_id: UUID, owner_id: UUID
    ) -> list[DeliveryAttempt]:
        attempts = await self._deliveries.get_by_event(event_id, cursor=None, limit=100)
        for a in attempts:
            endpoint = await self._endpoints.get_by_id(a.endpoint_id)
            if endpoint is None:
                continue
            if endpoint.owner_id != owner_id:
                raise ForbiddenError()
        return attempts

    async def create_pending_delivery(
        self, event_id: UUID, endpoint_id: UUID
    ) -> DeliveryAttempt:
        now = datetime.now(UTC)
        attempt = DeliveryAttempt(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            event_id=event_id,
            endpoint_id=endpoint_id,
            attempt_number=1,
            status=DeliveryStatus.PENDING,
            response_code=None,
            response_body=None,
            error_message=None,
            attempted_at=now,
        )
        return await self._deliveries.create(attempt)

    async def record_attempt(
        self,
        delivery_id: UUID,
        status: DeliveryStatus,
        response_code: int | None,
        response_body: str | None = None,
        error_message: str | None = None,
        attempted_at: datetime | None = None,
    ) -> DeliveryAttempt:
        attempt = await self._deliveries.get_by_id(delivery_id)
        if attempt is None:
            raise NotFoundError()

        attempt.status = status
        attempt.response_code = response_code
        attempt.response_body = (response_body or "")[:1000] or None
        attempt.error_message = error_message
        attempt.attempted_at = attempted_at or datetime.now(UTC)
        attempt.updated_at = datetime.now(UTC)
        return await self._deliveries.update(attempt)

    async def schedule_retry(self, delivery_id: UUID, attempt_number: int) -> None:
        current = await self._deliveries.get_by_id(delivery_id)
        if current is None:
            raise NotFoundError()

        delay_s = DELIVERY_RETRY_DELAYS_SECONDS[
            min(max(attempt_number - 1, 0), len(DELIVERY_RETRY_DELAYS_SECONDS) - 1)
        ]
        now = datetime.now(UTC)
        retry_at = now + timedelta(seconds=delay_s)

        next_attempt = DeliveryAttempt(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            event_id=current.event_id,
            endpoint_id=current.endpoint_id,
            attempt_number=attempt_number,
            status=DeliveryStatus.RETRYING,
            response_code=None,
            response_body=None,
            error_message=None,
            attempted_at=retry_at,
        )
        await self._deliveries.create(next_attempt)

