from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from src.core.dependencies import get_auth_service
from src.domain.entities.user import User
from src.services.auth_service import AuthService


async def get_current_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> User:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )
    user = await auth.verify_key(x_api_key)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return user

