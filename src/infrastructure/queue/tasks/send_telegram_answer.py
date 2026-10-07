import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from src.core.config import settings
from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.models.telegram_bot import TelegramBotModel as Bot
from src.infrastructure.db.repositories.telegram_answer_repository import (
    SendClaim,
    TelegramSendRepository,
)
from src.infrastructure.platform.clients import (
    AuthFortressClient,
    TelegramClient,
    TelegramSendError,
)
from src.infrastructure.platform.credentials import BotCredentials
from src.infrastructure.platform.errors import PlatformError
from src.infrastructure.queue.celery_app import celery_app

logger = logging.getLogger(__name__)


def _finish(
    claim: SendClaim,
    state: str,
    code: str | None,
    *,
    started: bool,
    message_id: int | None = None,
    retry_after: int = 0,
) -> None:
    try:
        with sync_session_maker() as db:
            TelegramSendRepository(db).finish(
                claim,
                state,
                code,
                started=started,
                message_id=message_id,
                retry_after=retry_after,
            )
            db.commit()
    except Exception:
        logger.warning("Telegram delivery outcome persistence unavailable")


@celery_app.task(
    name="send_telegram_answer",
    soft_time_limit=25,
    time_limit=30,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=0,
    ignore_result=True,
)  # type: ignore[untyped-decorator]
def send_telegram_answer(answer_id: str) -> None:
    if not settings.TELEGRAM_REPLIES_ENABLED:
        return
    try:
        identity = UUID(answer_id)
    except (TypeError, ValueError, AttributeError):
        logger.warning("Invalid Telegram delivery notification")
        return
    try:
        with sync_session_maker() as db:
            claim = TelegramSendRepository(db).claim(identity)
            db.commit()
    except Exception:
        logger.warning("Telegram delivery claim unavailable")
        return
    if claim is None:
        return
    started = False
    try:
        issuer = AuthFortressClient(
            settings.AUTHFORTRESS_BASE_URL or "",
            settings.AUTHFORTRESS_WEBHOOK_SERVICE_KEY,
        )
        asyncio.run(issuer.tenant_active(claim.tenant_id))
        with sync_session_maker() as db:
            bot = db.scalar(
                select(Bot)
                .where(
                    Bot.id == claim.bot_id,
                    Bot.tenant_id == claim.tenant_id,
                    Bot.is_active.is_(True),
                )
                .with_for_update()
            )
            if bot is None:
                _finish(claim, "cancelled", "inactive_context", started=False)
                return
            if settings.BOT_CREDENTIALS_KEY is None:
                raise ValueError("Missing credential key")
            token = BotCredentials(settings.BOT_CREDENTIALS_KEY).decrypt(
                bot.credentials_encrypted, claim.bot_id, claim.tenant_id
            )
            if not TelegramSendRepository(db).mark_started(claim):
                return
            db.commit()
        started = True
        result = asyncio.run(
            TelegramClient().send_message(token, claim.chat_id, claim.text)
        )
        _finish(claim, "succeeded", None, started=True, message_id=result.message_id)
    except TelegramSendError as error:
        _finish(
            claim,
            error.state,
            "send_retry_exhausted" if error.state == "pending" else "send_rejected",
            started=started,
            retry_after=error.retry_after,
        )
    except PlatformError as error:
        _finish(
            claim,
            "cancelled" if error.status_code == 403 else "pending",
            "context_unavailable",
            started=started,
        )
    except ValueError:
        _finish(claim, "failed", "invalid_delivery", started=started)
    except Exception:
        _finish(
            claim,
            "unknown" if started else "pending",
            "send_uncertain" if started else "presend_unavailable",
            started=started,
        )
