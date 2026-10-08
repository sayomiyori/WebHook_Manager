from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.v1.dependencies.auth import get_current_owner, get_current_user
from src.api.v1.schemas.deliveries import (
    DeliveryAttemptResponse,
    DeliveryDispatchRequest,
)
from src.api.v1.schemas.pagination import CursorPage
from src.core.dependencies import (
    get_delivery_service,
    get_endpoint_service,
    get_event_service,
    get_source_repo,
)
from src.domain.entities.user import User
from src.domain.interfaces.repositories import SourceRepository
from src.services.delivery_service import DeliveryService
from src.services.endpoint_service import EndpointService
from src.services.event_service import EventService

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.post(
    "",
    response_model=DeliveryAttemptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def dispatch_delivery(
    body: DeliveryDispatchRequest,
    current_user: User = Depends(get_current_user),  # noqa: B008
    events: EventService = Depends(get_event_service),  # noqa: B008
    endpoints: EndpointService = Depends(get_endpoint_service),  # noqa: B008
    sources: SourceRepository = Depends(get_source_repo),  # noqa: B008
    service: DeliveryService = Depends(get_delivery_service),  # noqa: B008
) -> DeliveryAttemptResponse:
    await endpoints.get_endpoint(body.endpoint_id, current_user.id)
    event = await events.get_event(body.event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    source = await sources.get_by_id(event.source_id)
    if source is None or source.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    attempt = await service.create_pending_delivery(body.event_id, body.endpoint_id)
    return DeliveryAttemptResponse.model_validate(attempt)


@router.get("", response_model=CursorPage[DeliveryAttemptResponse])
async def list_deliveries(
    event_id: UUID,
    owner_id: UUID = Depends(get_current_owner),  # noqa: B008
    cursor: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    service: DeliveryService = Depends(get_delivery_service),  # noqa: B008
) -> CursorPage[DeliveryAttemptResponse]:
    attempts = await service.get_delivery_history(
        event_id, owner_id, cursor=cursor, limit=limit
    )
    next_cursor = attempts[-1].id if len(attempts) == limit else None
    return CursorPage[DeliveryAttemptResponse](
        items=[DeliveryAttemptResponse.model_validate(a) for a in attempts],
        next_cursor=next_cursor,
    )


@router.post("/{attempt_id}/retry", response_model=DeliveryAttemptResponse)
async def retry_delivery(
    attempt_id: UUID,
    current_user: User = Depends(get_current_user),  # noqa: B008
    endpoints: EndpointService = Depends(get_endpoint_service),  # noqa: B008
    service: DeliveryService = Depends(get_delivery_service),  # noqa: B008
) -> DeliveryAttemptResponse:
    attempt = await service.get_delivery(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await endpoints.get_endpoint(attempt.endpoint_id, current_user.id)
    await service.schedule_retry(attempt_id, attempt.attempt_number + 1)
    refreshed = await service.get_delivery(attempt_id)
    return DeliveryAttemptResponse.model_validate(refreshed or attempt)
