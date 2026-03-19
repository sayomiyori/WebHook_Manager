from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import Response

from src.api.v1.dependencies.auth import get_current_user
from src.api.v1.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
)
from src.core.dependencies import get_auth_service
from src.domain.entities.user import User
from src.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> RegisterResponse:
    user = await auth.register_user(body.email, body.password)
    return RegisterResponse(user_id=user.id)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
async def login(
    body: LoginRequest,
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> LoginResponse:
    user = await auth.login_user(body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return LoginResponse(user_id=user.id)


@router.post(
    "/keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    body: ApiKeyCreateRequest,
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ApiKeyCreateResponse:
    api_key, plaintext = await auth.create_api_key(
        owner_id=body.owner_id,
        name=body.name,
    )
    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        created_at=api_key.created_at,
        key=plaintext,
    )


@router.get("/keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[ApiKeyResponse]:
    keys = await auth.list_api_keys(owner_id=current_user.id)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/keys/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    id: UUID,
    current_user: User = Depends(get_current_user),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> Response:
    await auth.revoke_api_key(key_id=id, owner_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

