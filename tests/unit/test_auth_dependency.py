from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException

from src.api.v1.dependencies.auth import get_current_user
from src.domain.entities.api_key import ApiKey
from src.domain.entities.user import User


def _user(*, is_active: bool = True) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        email="u@example.com",
        hashed_password="x",
        is_active=is_active,
    )


def _key(*, owner_id, is_active: bool = True) -> ApiKey:
    now = datetime.now(UTC)
    return ApiKey(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        key_prefix="wh",
        key_hash="hash",
        name="k",
        owner_id=owner_id,
        last_used_at=None,
        is_active=is_active,
    )


@pytest.mark.asyncio
async def test_get_current_user_401_when_missing_api_key() -> None:
    auth = Mock()
    user_repo = Mock()
    bg = BackgroundTasks()
    with pytest.raises(HTTPException) as exc:
        await get_current_user(
            background_tasks=bg,
            api_key=None,
            auth=auth,  # type: ignore[arg-type]
            user_repo=user_repo,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_401_when_verify_returns_none() -> None:
    auth = Mock()
    auth.verify_api_key = AsyncMock(return_value=None)
    auth.mark_key_used = AsyncMock()
    user_repo = Mock()
    bg = BackgroundTasks()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(
            background_tasks=bg,
            api_key="raw",
            auth=auth,  # type: ignore[arg-type]
            user_repo=user_repo,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_401_when_key_inactive() -> None:
    auth = Mock()
    owner_id = uuid4()
    auth.verify_api_key = AsyncMock(
        return_value=_key(owner_id=owner_id, is_active=False)
    )
    auth.mark_key_used = AsyncMock()
    user_repo = Mock()
    bg = BackgroundTasks()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(
            background_tasks=bg,
            api_key="raw",
            auth=auth,  # type: ignore[arg-type]
            user_repo=user_repo,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_403_when_user_missing_or_inactive() -> None:
    auth = Mock()
    owner_id = uuid4()
    auth.verify_api_key = AsyncMock(
        return_value=_key(owner_id=owner_id, is_active=True)
    )
    auth.mark_key_used = AsyncMock()
    user_repo = Mock()
    user_repo.get_by_id = AsyncMock(return_value=None)
    bg = BackgroundTasks()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(
            background_tasks=bg,
            api_key="raw",
            auth=auth,  # type: ignore[arg-type]
            user_repo=user_repo,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_current_user_success_adds_background_task() -> None:
    auth = Mock()
    owner_id = uuid4()
    key = _key(owner_id=owner_id, is_active=True)
    user = _user(is_active=True)
    user.id = owner_id

    auth.verify_api_key = AsyncMock(return_value=key)
    auth.mark_key_used = AsyncMock()
    user_repo = Mock()
    user_repo.get_by_id = AsyncMock(return_value=user)
    bg = BackgroundTasks()

    out = await get_current_user(
        background_tasks=bg,
        api_key="raw",
        auth=auth,  # type: ignore[arg-type]
        user_repo=user_repo,  # type: ignore[arg-type]
    )

    assert out.id == owner_id
    assert len(bg.tasks) == 1

