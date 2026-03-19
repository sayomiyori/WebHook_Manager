from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.api.middleware.correlation_id import CorrelationIdMiddleware
from src.api.middleware.request_logging import RequestLoggingMiddleware
from src.api.routers.health import router as health_router
from src.api.routers.metrics import router as metrics_router
from src.api.v1.routers import (
    auth_router,
    deliveries_router,
    endpoints_router,
    events_router,
    ingest_router,
    subscriptions_router,
)
from src.core.config import settings
from src.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
)
from src.core.logging import configure_logging
from src.infrastructure.cache.redis_client import get_redis
from src.infrastructure.db.base import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(debug=settings.DEBUG)
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=0.05,
            integrations=[FastApiIntegration(), CeleryIntegration()],
        )
    async with engine.connect():
        pass
    yield
    await engine.dispose()
    await get_redis().aclose()


app = FastAPI(title="Webhook Manager", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.TRUSTED_HOSTS or ["*"],
)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(NotFoundError)
async def handle_not_found(_: Request, __: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "not_found"})


@app.exception_handler(ForbiddenError)
async def handle_forbidden(_: Request, __: ForbiddenError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": "forbidden"})


@app.exception_handler(ConflictError)
async def handle_conflict(_: Request, __: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "conflict"})


@app.exception_handler(RateLimitError)
async def handle_rate_limit(_: Request, __: RateLimitError) -> JSONResponse:
    return JSONResponse(status_code=429, content={"error": "rate_limited"})

app.include_router(health_router)
app.include_router(metrics_router)

v1 = APIRouter(prefix="/api/v1")
v1.include_router(auth_router)
v1.include_router(deliveries_router)
v1.include_router(endpoints_router)
v1.include_router(events_router)
v1.include_router(subscriptions_router)
app.include_router(v1)

webhooks = APIRouter(prefix="/webhooks")
webhooks.include_router(ingest_router)
app.include_router(webhooks)

