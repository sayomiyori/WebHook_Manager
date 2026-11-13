from __future__ import annotations

from fastapi import APIRouter, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from src.core.config import settings

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    if (
        settings.PLATFORM_BOTS_ENABLED
        or settings.PLATFORM_TELEGRAM_ENABLED
        or settings.TELEGRAM_REPLIES_ENABLED
    ):
        raise HTTPException(
            status_code=503, detail="Global metrics disabled in platform mode"
        )
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
