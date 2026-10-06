from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import ClientDisconnect

from src.api.v1.dependencies.platform import get_ingress_service, require_telegram
from src.api.v1.schemas.telegram_ingress import IngressAck
from src.infrastructure.platform.errors import PlatformError
from src.infrastructure.platform.telegram_update import parse_update
from src.services.telegram_ingress_service import TelegramIngressService


class TelegramRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except (RequestValidationError, ValueError, RecursionError):
                return JSONResponse(
                    status_code=422, content={"detail": "Invalid Telegram update"}
                )
            except SQLAlchemyError:
                return JSONResponse(
                    status_code=503, content={"detail": "Service unavailable"}
                )
            except ClientDisconnect:
                return JSONResponse(
                    status_code=400, content={"detail": "Incomplete Telegram update"}
                )

        return guarded


router = APIRouter(
    prefix="/webhooks/telegram",
    tags=["Telegram intake"],
    route_class=TelegramRoute,
    dependencies=[Depends(require_telegram)],
)


@router.post("/{bot_id}", response_model=IngressAck)
async def receive_update(
    bot_id: UUID,
    request: Request,
    service: TelegramIngressService = Depends(get_ingress_service),  # noqa: B008
) -> JSONResponse:  # noqa: B008
    values = request.headers.getlist("X-Telegram-Bot-Api-Secret-Token")
    if len(values) != 1:
        raise PlatformError(401)
    secret = SecretStr(values[0])
    await service.authenticate(bot_id, secret)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
        or request.headers.get("content-encoding", "identity").lower() != "identity"
    ):
        return JSONResponse(
            status_code=415, content={"detail": "Unsupported Telegram content"}
        )
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 1048576:
            return JSONResponse(
                status_code=413, content={"detail": "Telegram update too large"}
            )
        body.extend(chunk)
    event, duplicate = await service.admit(bot_id, secret, parse_update(bytes(body)))
    status = (
        "duplicate"
        if duplicate
        else "ignored"
        if event.state == "ignored"
        else "accepted"
    )
    return JSONResponse(
        status_code=202 if status == "accepted" else 200,
        content={"status": status, "event_id": str(event.id)},
    )
