from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.v1.dependencies.auth import get_current_user
from src.api.v1.dependencies.rate_limit import rate_limit_ingest, rate_limit_read
from src.api.v1.schemas.events import EventIngestRequest, WebhookEventResponse
from src.api.v1.schemas.pagination import CursorPage
from src.core.dependencies import get_event_service, get_source_repo
from src.core.security import sanitize_webhook_headers
from src.domain.entities.user import User
from src.domain.interfaces.repositories import SourceRepository
from src.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "",
    response_model=WebhookEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_event(
    body: EventIngestRequest,
    current_user: User = Depends(get_current_user),  # noqa: B008
    sources: SourceRepository = Depends(get_source_repo),  # noqa: B008
    service: EventService = Depends(get_event_service),  # noqa: B008
    _: None = Depends(rate_limit_ingest),  # noqa: B008
) -> WebhookEventResponse:
    source = await sources.get_by_id(body.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    event, _dup = await service.ingest_event(
        body.source_id,
        body.payload,
        sanitize_webhook_headers(body.headers),
        body.idempotency_key,
        body.event_type,
    )
    return WebhookEventResponse.model_validate(event)


@router.get("/{event_id}", response_model=WebhookEventResponse)
async def get_event(
    event_id: UUID,
    current_user: User = Depends(get_current_user),  # noqa: B008
    sources: SourceRepository = Depends(get_source_repo),  # noqa: B008
    service: EventService = Depends(get_event_service),  # noqa: B008
    _: None = Depends(rate_limit_read),  # noqa: B008
) -> WebhookEventResponse:
    event = await service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    source = await sources.get_by_id(event.source_id)
    if source is None or source.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return WebhookEventResponse.model_validate(event)


@router.get("", response_model=CursorPage[WebhookEventResponse])
async def list_events(
    source_id: UUID,
    cursor: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),  # noqa: B008
    sources: SourceRepository = Depends(get_source_repo),  # noqa: B008
    service: EventService = Depends(get_event_service),  # noqa: B008
    _: None = Depends(rate_limit_read),  # noqa: B008
) -> CursorPage[WebhookEventResponse]:
    source = await sources.get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    items, next_cursor = await service.list_events_by_source(
        source_id, cursor=cursor, limit=limit
    )
    return CursorPage[WebhookEventResponse](
        items=[WebhookEventResponse.model_validate(e) for e in items],
        next_cursor=next_cursor,
    )
