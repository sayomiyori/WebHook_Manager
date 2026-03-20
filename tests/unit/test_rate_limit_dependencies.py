from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.api.v1.dependencies.rate_limit import rate_limit_ingest, rate_limit_read


@pytest.mark.asyncio
async def test_rate_limit_ingest_skips_when_no_api_key() -> None:
    limiter = AsyncMock()
    await rate_limit_ingest(x_api_key=None, limiter=limiter)  # type: ignore[arg-type]
    limiter.allow.assert_not_called()


@pytest.mark.asyncio
async def test_rate_limit_ingest_raises_when_exceeded() -> None:
    limiter = AsyncMock()
    limiter.allow = AsyncMock(return_value=False)
    with pytest.raises(HTTPException) as exc:
        await rate_limit_ingest(x_api_key="wh_1234567890", limiter=limiter)  # type: ignore[arg-type]
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_read_allows_when_within_limit() -> None:
    limiter = AsyncMock()
    limiter.allow = AsyncMock(return_value=True)
    await rate_limit_read(x_api_key="wh_1234567890", limiter=limiter)  # type: ignore[arg-type]
    limiter.allow.assert_awaited_once()

