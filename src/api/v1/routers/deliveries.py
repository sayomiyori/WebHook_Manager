from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.v1.schemas.deliveries import (
    DeliveryAttemptResponse,
    DeliveryDispatchRequest,
)
from src.api.v1.schemas.pagination import CursorPage
from src.core.dependencies import get_delivery_service
from src.services.delivery_service import DeliveryService

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.post(
    "",
    response_model=DeliveryAttemptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def dispatch_delivery(
    body: DeliveryDispatchRequest,
    service: DeliveryService = Depends(get_delivery_service),  # noqa: B008
) -> DeliveryAttemptResponse:
    attempt = await service.create_pending_delivery(body.event_id, body.endpoint_id)
    return DeliveryAttemptResponse.model_validate(attempt)


@router.get("", response_model=CursorPage[DeliveryAttemptResponse])
async def list_deliveries(
    event_id: UUID,
    owner_id: UUID,
    cursor: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    service: DeliveryService = Depends(get_delivery_service),  # noqa: B008
) -> CursorPage[DeliveryAttemptResponse]:
    # history in service is owner-scoped; cursor/limit not included in spec
    attempts = await service.get_delivery_history(event_id, owner_id)
    next_cursor = attempts[-1].id if len(attempts) == limit else None
    return CursorPage[DeliveryAttemptResponse](
        items=[DeliveryAttemptResponse.model_validate(a) for a in attempts],
        next_cursor=next_cursor,
    )


@router.post("/{attempt_id}/retry", response_model=DeliveryAttemptResponse)
async def retry_delivery(
    attempt_id: UUID,
    service: DeliveryService = Depends(get_delivery_service),  # noqa: B008
) -> DeliveryAttemptResponse:
    attempt = await service.get_delivery(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await service.schedule_retry(attempt_id, attempt.attempt_number + 1)
    refreshed = await service.get_delivery(attempt_id)
    return DeliveryAttemptResponse.model_validate(refreshed or attempt)

