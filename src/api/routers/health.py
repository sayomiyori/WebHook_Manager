from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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
async def health_ready() -> JSONResponse:
    db_ok = await check_db_health()
    redis_ok = False
    try:
        redis_ok = bool(await get_redis().ping())
    except Exception:  # noqa: BLE001
        redis_ok = False

    payload = {
        "status": "ok" if (db_ok and redis_ok) else "unavailable",
        "database": "ok" if db_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
    }
    status_code = 200 if (db_ok and redis_ok) else 503
    return JSONResponse(status_code=status_code, content=payload)

