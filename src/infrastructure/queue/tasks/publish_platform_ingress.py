from __future__ import annotations

import asyncio
import json
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from src.api.v1.schemas.telegram_ingress import TelegramIngressEnvelope
from src.core.config import settings
from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.models.telegram_bot import TelegramBotModel as Bot
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel as Event,
)
from src.infrastructure.db.repositories.platform_outbox_repository import (
    PlatformOutboxRepository,
)
from src.infrastructure.platform.agent_admission import (
    AdmissionError,
    AgentAdmissionClient,
)
from src.infrastructure.platform.clients import AuthFortressClient
from src.infrastructure.platform.errors import PlatformError
from src.infrastructure.queue.celery_app import celery_app


@celery_app.task(
    name="publish_platform_ingress", max_retries=0, soft_time_limit=15, time_limit=20
)  # type: ignore[untyped-decorator]
def publish_platform_ingress(outbox_id: str) -> dict[str, str]:
    try:
        settings.require_publication()
        return _publish(UUID(outbox_id))
    except (ValueError, SQLAlchemyError):
        return {"status": "publication_unavailable"}


def _publish(outbox_id: UUID) -> dict[str, str]:
    with sync_session_maker() as session:
        repo = PlatformOutboxRepository(session)
        row = repo.claim(outbox_id, settings.PLATFORM_PUBLICATION_MAX_ATTEMPTS)
        session.commit()
        if row is None or row.claim_id is None:
            return {"status": "not_claimed"}
        claim_id, tenant_id, bot_id = row.claim_id, row.tenant_id, row.bot_id
        event = session.get(Event, row.ingress_id)
        bot = session.get(Bot, bot_id)
        if (
            event is None
            or bot is None
            or event.tenant_id != tenant_id
            or event.bot_id != bot_id
            or bot.tenant_id != tenant_id
        ):
            repo.fail(
                outbox_id,
                claim_id,
                "invalid_canonical_context",
                True,
                None,
                settings.PLATFORM_PUBLICATION_MAX_ATTEMPTS,
            )
            session.commit()
            return {"status": "failed"}
        if not bot.is_active:
            repo.cancel(outbox_id, claim_id)
            session.commit()
            return {"status": "cancelled"}
        try:
            envelope = TelegramIngressEnvelope.model_validate_json(
                json.dumps(event.envelope)
            )
            if (
                envelope.event_id != event.id
                or envelope.tenant_id != tenant_id
                or envelope.bot_id != bot_id
            ):
                raise ValueError()
        except ValueError:
            repo.fail(
                outbox_id,
                claim_id,
                "invalid_envelope",
                True,
                None,
                settings.PLATFORM_PUBLICATION_MAX_ATTEMPTS,
            )
            session.commit()
            return {"status": "failed"}
    issuer = AuthFortressClient(
        settings.AUTHFORTRESS_BASE_URL or "", settings.AUTHFORTRESS_WEBHOOK_SERVICE_KEY
    )
    try:
        asyncio.run(issuer.tenant_active(tenant_id))
        with sync_session_maker() as session:
            bot = session.get(Bot, bot_id)
            if bot is None or not bot.is_active or bot.tenant_id != tenant_id:
                raise PlatformError(403)
        receipt = asyncio.run(AgentAdmissionClient(settings).admit(envelope))
    except PlatformError as error:
        with sync_session_maker() as session:
            repo = PlatformOutboxRepository(session)
            if error.status_code == 403:
                repo.cancel(outbox_id, claim_id)
                state = "cancelled"
            else:
                repo.fail(
                    outbox_id,
                    claim_id,
                    "issuer_unavailable",
                    False,
                    None,
                    settings.PLATFORM_PUBLICATION_MAX_ATTEMPTS,
                )
                state = "deferred"
            session.commit()
        return {"status": state}
    except AdmissionError as error:
        with sync_session_maker() as session:
            PlatformOutboxRepository(session).fail(
                outbox_id,
                claim_id,
                error.code,
                error.terminal,
                error.retry_after,
                settings.PLATFORM_PUBLICATION_MAX_ATTEMPTS,
            )
            session.commit()
        return {"status": "failed" if error.terminal else "deferred"}
    with sync_session_maker() as session:
        finished = PlatformOutboxRepository(session).finish(
            outbox_id, claim_id, receipt
        )
        session.commit()
    return {"status": "published" if finished else "stale_claim"}
