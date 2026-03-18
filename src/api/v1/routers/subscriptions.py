from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.v1.dependencies.rate_limit import rate_limit_read
from src.api.v1.schemas.pagination import CursorPage
from src.api.v1.schemas.subscriptions import (
    SubscriptionCreateRequest,
    SubscriptionResponse,
    SubscriptionUpdateRequest,
)
from src.core.dependencies import get_subscription_service
from src.services.subscription_service import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post(
    "",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    body: SubscriptionCreateRequest,
    service: SubscriptionService = Depends(get_subscription_service),  # noqa: B008
) -> SubscriptionResponse:
    subscription = await service.create(
        owner_id=body.owner_id,
        endpoint_id=body.endpoint_id,
        source_id=body.source_id,
        event_type_filter=body.event_type_filter,
        is_active=body.is_active,
    )
    return SubscriptionResponse.model_validate(subscription)


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(
    subscription_id: UUID,
    service: SubscriptionService = Depends(get_subscription_service),  # noqa: B008
    _: None = Depends(rate_limit_read),  # noqa: B008
) -> SubscriptionResponse:
    subscription = await service.get(subscription_id)
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return SubscriptionResponse.model_validate(subscription)


@router.get("", response_model=CursorPage[SubscriptionResponse])
async def list_subscriptions(
    owner_id: UUID,
    cursor: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    service: SubscriptionService = Depends(get_subscription_service),  # noqa: B008
    _: None = Depends(rate_limit_read),  # noqa: B008
) -> CursorPage[SubscriptionResponse]:
    items = await service.list_by_owner(owner_id, cursor=cursor, limit=limit)
    next_cursor = items[-1].id if len(items) == limit else None
    return CursorPage[SubscriptionResponse](
        items=[SubscriptionResponse.model_validate(s) for s in items],
        next_cursor=next_cursor,
    )


@router.put("/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: UUID,
    body: SubscriptionUpdateRequest,
    service: SubscriptionService = Depends(get_subscription_service),  # noqa: B008
) -> SubscriptionResponse:
    current = await service.get(subscription_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    updated = current
    if body.event_type_filter is not None:
        updated.event_type_filter = list(body.event_type_filter)
    if body.is_active is not None:
        updated.is_active = body.is_active

    saved = await service.update(updated)
    return SubscriptionResponse.model_validate(saved)


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_id: UUID,
    service: SubscriptionService = Depends(get_subscription_service),  # noqa: B008
) -> None:
    await service.delete(subscription_id)

