from __future__ import annotations

from fastapi import BackgroundTasks, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.core.dependencies import get_auth_service, get_user_repo
from src.domain.entities.user import User
from src.domain.interfaces.repositories import UserRepository
from src.services.auth_service import AuthService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    background_tasks: BackgroundTasks,
    api_key: str | None = Security(api_key_header),
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
    user_repo: UserRepository = Depends(get_user_repo),  # noqa: B008
) -> User:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )
    api_key_entity = await auth.verify_api_key(api_key)
    if api_key_entity is None or not api_key_entity.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    background_tasks.add_task(auth.mark_key_used, api_key_entity.id)

    user = await user_repo.get_by_id(api_key_entity.owner_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not found or inactive",
        )
    return user

