from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from src.api.v1.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
)
from src.api.v1.schemas.pagination import CursorPage
from src.core.dependencies import get_auth_service
from src.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    body: ApiKeyCreateRequest,
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ApiKeyCreateResponse:
    api_key, raw = await auth.generate_key(owner_id=body.owner_id, name=body.name)
    base = ApiKeyResponse.model_validate(api_key).model_dump()
    return ApiKeyCreateResponse.model_validate({**base, "raw_key": raw})


@router.get("/api-keys", response_model=CursorPage[ApiKeyResponse])
async def list_api_keys(
    owner_id: UUID,
    cursor: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> CursorPage[ApiKeyResponse]:
    keys = await auth.list_keys(owner_id=owner_id, cursor=cursor, limit=limit)
    next_cursor = keys[-1].id if len(keys) == limit else None
    return CursorPage[ApiKeyResponse](
        items=[ApiKeyResponse.model_validate(k) for k in keys],
        next_cursor=next_cursor,
    )


@router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    api_key_id: UUID,
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> None:
    await auth.revoke_key(api_key_id)

