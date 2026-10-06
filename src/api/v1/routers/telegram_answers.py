import hashlib
import hmac
import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies.platform import get_issuer, get_platform_settings
from src.api.v1.routers.telegram_ingress import TelegramRoute
from src.api.v1.schemas.telegram_answers import AnswerEnvelope, AnswerReceipt
from src.core.config import Settings
from src.core.dependencies import get_session
from src.infrastructure.db.repositories.telegram_answer_repository import (
    AnswerConflict,
    IngressNotReady,
    TelegramAnswerRepository,
)
from src.infrastructure.platform.clients import AuthFortressClient
from src.infrastructure.platform.errors import PlatformError
from src.infrastructure.platform.telegram_update import parse_update
from src.services.telegram_answer_service import TelegramAnswerService


def require_answers(config: Settings = Depends(get_platform_settings)) -> Settings:  # noqa: B008
    if (
        not config.TELEGRAM_REPLIES_ENABLED
        or config.AGENT_WEBHOOK_REPLY_KEY is None
    ):
        raise PlatformError()
    return config


def get_answer_service(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    issuer: AuthFortressClient = Depends(get_issuer),  # noqa: B008
) -> TelegramAnswerService:
    return TelegramAnswerService(TelegramAnswerRepository(session), issuer)


router = APIRouter(
    prefix="/internal/v1/telegram", tags=["Telegram answers"], route_class=TelegramRoute
)


@router.post("/answers", response_model=AnswerReceipt)
async def receive_answer(
    request: Request,
    config: Settings = Depends(require_answers),  # noqa: B008
    service: TelegramAnswerService = Depends(get_answer_service),  # noqa: B008
) -> JSONResponse:
    values = request.headers.getlist("X-Webhook-Signature")
    if len(values) != 1 or re.fullmatch(r"sha256=[0-9a-f]{64}", values[0]) is None:
        raise PlatformError(401)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
        or request.headers.get("content-encoding", "identity").lower() != "identity"
    ):
        return JSONResponse(
            status_code=415, content={"detail": "Unsupported answer content"}
        )
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 1048576:
            return JSONResponse(status_code=413, content={"detail": "Answer too large"})
        body.extend(chunk)
    assert config.AGENT_WEBHOOK_REPLY_KEY is not None
    expected = hmac.new(
        config.AGENT_WEBHOOK_REPLY_KEY.get_secret_value().encode("ascii"),
        bytes(body),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(values[0][7:], expected):
        raise PlatformError(401)
    envelope = AnswerEnvelope.model_validate_json(json.dumps(parse_update(bytes(body))))
    try:
        receipt, created = await service.admit(envelope)
    except IngressNotReady:
        return JSONResponse(
            status_code=409, content={"detail": "ingress_publication_not_ready"}
        )
    except AnswerConflict:
        return JSONResponse(status_code=409, content={"detail": "answer_conflict"})
    return JSONResponse(
        status_code=202 if created else 200, content=receipt.model_dump(mode="json")
    )
