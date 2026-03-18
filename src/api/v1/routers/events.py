from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.v1.dependencies.rate_limit import rate_limit_ingest, rate_limit_read
from src.api.v1.schemas.events import EventIngestRequest, WebhookEventResponse
from src.api.v1.schemas.pagination import CursorPage
from src.core.dependencies import get_event_service
from src.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "",
    response_model=WebhookEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_event(
    body: EventIngestRequest,
    service: EventService = Depends(get_event_service),  # noqa: B008
    _: None = Depends(rate_limit_ingest),  # noqa: B008
) -> WebhookEventResponse:
    event, _dup = await service.ingest_event(
        body.source_id,
        body.payload,
        body.headers,
        body.idempotency_key,
        body.event_type,
    )
    return WebhookEventResponse.model_validate(event)


@router.get("/{event_id}", response_model=WebhookEventResponse)
async def get_event(
    event_id: UUID,
    service: EventService = Depends(get_event_service),  # noqa: B008
    _: None = Depends(rate_limit_read),  # noqa: B008
) -> WebhookEventResponse:
    event = await service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return WebhookEventResponse.model_validate(event)


@router.get("", response_model=CursorPage[WebhookEventResponse])
async def list_events(
    source_id: UUID,
    cursor: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    service: EventService = Depends(get_event_service),  # noqa: B008
    _: None = Depends(rate_limit_read),  # noqa: B008
) -> CursorPage[WebhookEventResponse]:
    items, next_cursor = await service.list_events_by_source(
        source_id, cursor=cursor, limit=limit
    )
    return CursorPage[WebhookEventResponse](
        items=[WebhookEventResponse.model_validate(e) for e in items],
        next_cursor=next_cursor,
    )

