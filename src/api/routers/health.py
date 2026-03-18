from __future__ import annotations

from fastapi import APIRouter

from src.infrastructure.db.base import check_db_health

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/health/db")
async def health_db() -> dict[str, bool]:
    return {"ok": await check_db_health()}

