from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)

from src.api.v1.dependencies.rate_limit import rate_limit_ingest
from src.core.dependencies import (
    get_event_service,
    get_source_repo,
)
from src.core.metrics import webhooks_received_total
from src.core.security import verify_hmac_signature
from src.domain.interfaces.repositories import SourceRepository
from src.infrastructure.queue.dispatcher import dispatch_event_deliveries
from src.services.event_service import EventService

log = structlog.get_logger()

router = APIRouter(tags=["ingest"])

MAX_BODY_BYTES = 1_048_576


async def _dispatch_deliveries(
    *,
    event_service: EventService,
    event_id_str: str,
) -> None:
    # Re-fetch event so this background task is independent from request scope.
    from uuid import UUID

    event = await event_service.get_event(UUID(event_id_str))
    if event is None:
        return
    subs = await event_service.get_matching_subscriptions(event)
    await dispatch_event_deliveries(event, subs)


@router.post("/ingest/{source_slug}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_webhook(
    source_slug: str,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    source_repo: SourceRepository = Depends(get_source_repo),  # noqa: B008
    event_service: EventService = Depends(get_event_service),  # noqa: B008
    _: None = Depends(rate_limit_ingest),  # noqa: B008
) -> dict[str, str]:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    source = await source_repo.get_by_slug_global(source_slug)
    if source is None or not source.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not found",
        )

    signature = request.headers.get("X-Webhook-Signature", "")
    if source.secret:
        if not verify_hmac_signature(body, source.secret, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bad signature",
            )

    idempotency_key = request.headers.get("X-Idempotency-Key")
    event_type = request.headers.get("X-Event-Type")

    try:
        payload_obj: Any = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON",
        ) from exc

    if not isinstance(payload_obj, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must be object",
        )

    headers = {k: v for k, v in request.headers.items()}

    event, duplicate = await event_service.ingest_event(
        source.id,
        payload_obj,
        headers,
        idempotency_key,
        event_type,
    )

    log.info(
        "ingest",
        source=source.slug,
        event_type=event.event_type,
        idempotency_key=idempotency_key,
        duplicate=duplicate,
    )
    webhooks_received_total.labels(
        source=source.slug,
        event_type=event.event_type or "unknown",
    ).inc()

    if duplicate:
        response.status_code = status.HTTP_200_OK
        return {"status": "duplicate", "event_id": str(event.id)}

    # Fire-and-forget: schedule downstream dispatch after response.
    # NOTE: we intentionally avoid blocking the request path.
    background_tasks.add_task(
        _dispatch_deliveries,
        event_service=event_service,
        event_id_str=str(event.id),
    )
    return {"status": "accepted", "event_id": str(event.id)}

