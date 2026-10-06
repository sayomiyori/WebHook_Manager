from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from src.api.v1.dependencies.platform import (
    get_bearer,
    get_bot_service,
    get_webhook_service,
    require_manage,
    require_platform,
    require_read,
    require_service_key,
)
from src.api.v1.schemas.bots import (
    BotContext,
    BotCreate,
    BotView,
    WebhookProvisionRequest,
    WebhookProvisionView,
)
from src.api.v1.schemas.pagination import CursorPage
from src.services.bot_service import BotService
from src.services.telegram_webhook_service import TelegramWebhookService


class BotRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 4096:
                    return JSONResponse(
                        status_code=422, content={"detail": "Invalid bot request"}
                    )
                body.extend(chunk)
            request._body = bytes(body)
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422, content={"detail": "Invalid bot request"}
                )
            except SQLAlchemyError:
                # DB exception parameters may include encrypted credentials.
                return JSONResponse(
                    status_code=503, content={"detail": "Service unavailable"}
                )

        return guarded


router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/bots",
    tags=["platform bots"],
    route_class=BotRoute,
    dependencies=[Depends(require_platform)],
)
internal_router = APIRouter(
    prefix="/internal/v1/bots",
    tags=["internal bots"],
    route_class=BotRoute,
    dependencies=[Depends(require_service_key)],
)


@router.post("/{bot_id}/webhook", response_model=WebhookProvisionView)
async def provision_webhook(
    tenant_id: UUID,
    bot_id: UUID,
    body: WebhookProvisionRequest,
    bearer: SecretStr = Depends(get_bearer),  # noqa: B008
    service: TelegramWebhookService = Depends(get_webhook_service),  # noqa: B008
) -> WebhookProvisionView:  # noqa: B008
    return await service.provision(tenant_id, bot_id, bearer, body.dry_run)


@router.post("", response_model=BotView, status_code=201)
async def create_bot(
    tenant_id: UUID,
    body: BotCreate,
    bearer: SecretStr = Depends(get_bearer),  # noqa: B008
    service: BotService = Depends(get_bot_service),  # noqa: B008
) -> BotView:
    return BotView.model_validate(
        await service.create(tenant_id, bearer, body.name, body.token)
    )


@router.get(
    "", response_model=CursorPage[BotView], dependencies=[Depends(require_read)]
)
async def list_bots(
    tenant_id: UUID,
    cursor: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    service: BotService = Depends(get_bot_service),  # noqa: B008
) -> CursorPage[BotView]:
    items = await service.list(tenant_id, cursor, limit)
    return CursorPage[BotView](
        items=[BotView.model_validate(item) for item in items],
        next_cursor=items[-1].id if len(items) == limit else None,
    )


@router.get("/{bot_id}", response_model=BotView, dependencies=[Depends(require_read)])
async def read_bot(
    tenant_id: UUID,
    bot_id: UUID,
    service: BotService = Depends(get_bot_service),  # noqa: B008
) -> BotView:
    return BotView.model_validate(await service.get(bot_id, tenant_id))


@router.post(
    "/{bot_id}/deactivate",
    response_model=BotView,
    dependencies=[Depends(require_manage)],
)
async def deactivate_bot(
    tenant_id: UUID,
    bot_id: UUID,
    service: BotService = Depends(get_bot_service),  # noqa: B008
) -> BotView:
    return BotView.model_validate(await service.deactivate(bot_id, tenant_id))


@internal_router.get("/{bot_id}/context", response_model=BotContext)
async def bot_context(
    bot_id: UUID,
    service: BotService = Depends(get_bot_service),  # noqa: B008
) -> BotContext:
    bot = await service.context(bot_id)
    return BotContext(
        bot_id=bot.id, tenant_id=bot.tenant_id, telegram_bot_id=bot.telegram_bot_id
    )
