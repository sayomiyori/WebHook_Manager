from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.infrastructure.cache.redis_client import get_redis
from src.infrastructure.db.base import check_db_health

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready() -> dict[str, object]:
    db_ok = await check_db_health()
    redis_ok = False
    try:
        redis_ok = bool(await get_redis().ping())
    except Exception:
        redis_ok = False

    if db_ok and redis_ok:
        return {"status": "ok", "db": True, "redis": True}

    detail: dict[str, object] = {"db": db_ok, "redis": redis_ok}
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
    )

