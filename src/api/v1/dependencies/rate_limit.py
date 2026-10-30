from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from src.core.config import settings
from src.core.dependencies import get_rate_limiter
from src.infrastructure.cache.rate_limiter import RateLimiter

AUTH_RATE_LIMIT = 60


async def rate_limit_auth(
    request: Request,
    limiter: RateLimiter = Depends(get_rate_limiter),  # noqa: B008
) -> None:
    host = request.client.host if request.client else "unknown"
    ok = await limiter.allow(
        key=f"auth:{host}", limit=AUTH_RATE_LIMIT, count_denied=False
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )


async def rate_limit_ingest(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    limiter: RateLimiter = Depends(get_rate_limiter),  # noqa: B008
) -> None:
    if not x_api_key:
        return
    ok = await limiter.allow(
        key=f"ingest:{x_api_key[:8]}",
        limit=settings.RATE_LIMIT_INGEST,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )


async def rate_limit_read(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    limiter: RateLimiter = Depends(get_rate_limiter),  # noqa: B008
) -> None:
    if not x_api_key:
        return
    ok = await limiter.allow(
        key=f"read:{x_api_key[:8]}",
        limit=settings.RATE_LIMIT_READ,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )

