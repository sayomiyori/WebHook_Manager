from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.dependencies import get_rate_limiter, get_session


async def _fake_session():
    yield None


@pytest.mark.asyncio
async def test_auth_routes_use_the_shared_limiter_before_handlers() -> None:
    limiter = AsyncMock()
    limiter.allow = AsyncMock(return_value=False)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_session] = _fake_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            for path, payload in (
                (
                    "/api/v1/auth/login",
                    {"email": "user@example.com", "password": "wrong"},
                ),
                (
                    "/api/v1/auth/register",
                    {"email": "user@example.com", "password": "secret12"},
                ),
            ):
                response = await client.post(path, json=payload)
                assert response.status_code == 429
    finally:
        app.dependency_overrides.clear()
    assert limiter.allow.await_count == 2
    for call in limiter.allow.await_args_list:
        assert call.kwargs["limit"] == 60
        assert call.kwargs["key"].startswith("auth:")
        assert call.kwargs["count_denied"] is False


@pytest.mark.asyncio
async def test_rate_limiter_runs_before_body_validation() -> None:
    limiter = AsyncMock()
    limiter.allow = AsyncMock(return_value=True)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_session] = _fake_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "bad", "password": ""},
            )
            assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
    assert limiter.allow.await_count == 1
