from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.v1.dependencies.auth import get_current_user
from src.api.v1.dependencies.rate_limit import rate_limit_read
from src.api.v1.schemas.endpoints import (
    EndpointCreateRequest,
    EndpointResponse,
    EndpointUpdateRequest,
)
from src.api.v1.schemas.pagination import CursorPage
from src.core.dependencies import get_endpoint_service
from src.core.exceptions import ForbiddenError, NotFoundError
from src.domain.entities.user import User
from src.services.endpoint_service import EndpointService

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


@router.post("", response_model=EndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    body: EndpointCreateRequest,
    current_user: User = Depends(get_current_user),  # noqa: B008
    service: EndpointService = Depends(get_endpoint_service),  # noqa: B008
) -> EndpointResponse:
    endpoint = await service.create_endpoint(
        owner_id=current_user.id, name=body.name, url=body.url, secret=body.secret
    )
    return EndpointResponse.model_validate(endpoint)


@router.get("/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(
    endpoint_id: UUID,
    owner_id: UUID,
    service: EndpointService = Depends(get_endpoint_service),  # noqa: B008
    _: None = Depends(rate_limit_read),  # noqa: B008
) -> EndpointResponse:
    try:
        endpoint = await service.get_endpoint(endpoint_id, owner_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        ) from exc
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
        ) from exc
    return EndpointResponse.model_validate(endpoint)


@router.get("", response_model=CursorPage[EndpointResponse])
async def list_endpoints(
    owner_id: UUID,
    cursor: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    service: EndpointService = Depends(get_endpoint_service),  # noqa: B008
    _: None = Depends(rate_limit_read),  # noqa: B008
) -> CursorPage[EndpointResponse]:
    items, next_cursor = await service.list_endpoints(owner_id, cursor, limit)
    return CursorPage[EndpointResponse](
        items=[EndpointResponse.model_validate(e) for e in items],
        next_cursor=next_cursor,
    )


@router.put("/{endpoint_id}", response_model=EndpointResponse)
async def update_endpoint(
    endpoint_id: UUID,
    owner_id: UUID,
    body: EndpointUpdateRequest,
    service: EndpointService = Depends(get_endpoint_service),  # noqa: B008
) -> EndpointResponse:
    fields: dict[str, object] = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.url is not None:
        fields["url"] = body.url
    if body.is_active is not None:
        fields["is_active"] = body.is_active
    if "secret" in body.model_fields_set:
        fields["secret"] = body.secret

    saved = await service.update_endpoint(endpoint_id, owner_id, **fields)
    return EndpointResponse.model_validate(saved)


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    endpoint_id: UUID,
    owner_id: UUID,
    service: EndpointService = Depends(get_endpoint_service),  # noqa: B008
) -> None:
    await service.delete_endpoint(endpoint_id, owner_id)

