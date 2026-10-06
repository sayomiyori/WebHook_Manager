import json

from sqlalchemy import select

from src.api.v1.schemas.telegram_answers import AnswerEnvelope, AnswerReceipt
from src.api.v1.schemas.telegram_ingress import TelegramIngressEnvelope
from src.infrastructure.db.models.platform_ingress_outbox import (
    PlatformIngressOutboxModel as Outbox,
)
from src.infrastructure.db.models.telegram_bot import TelegramBotModel as Bot
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel as Ingress,
)
from src.infrastructure.db.repositories.telegram_answer_repository import (
    AnswerConflict,
    IngressNotReady,
    TelegramAnswerRepository,
)
from src.infrastructure.platform.clients import AuthFortressClient
from src.infrastructure.platform.errors import PlatformError


class TelegramAnswerService:
    def __init__(
        self, repo: TelegramAnswerRepository, issuer: AuthFortressClient
    ) -> None:
        self.repo, self.issuer = repo, issuer

    async def admit(self, envelope: AnswerEnvelope) -> tuple[AnswerReceipt, bool]:
        db = self.repo.session
        try:
            ingress = await db.scalar(
                select(Ingress).where(
                    Ingress.id == envelope.payload.ingress_event_id,
                    Ingress.tenant_id == envelope.tenant_id,
                    Ingress.bot_id == envelope.bot_id,
                    Ingress.state == "accepted",
                )
            )
            if ingress is None:
                raise PlatformError(404)
            if ingress.correlation_id != envelope.correlation_id:
                raise AnswerConflict()
            publication = await db.scalar(
                select(Outbox).where(
                    Outbox.ingress_id == ingress.id,
                    Outbox.tenant_id == envelope.tenant_id,
                    Outbox.bot_id == envelope.bot_id,
                )
            )
            if publication is None:
                raise PlatformError(404)
            if publication.state != "published" or publication.published_job_id is None:
                raise IngressNotReady()
            if publication.published_job_id != envelope.payload.job_id:
                raise AnswerConflict()
            original = TelegramIngressEnvelope.model_validate_json(
                json.dumps(ingress.envelope)
            )
            if (
                original.event_id != ingress.id
                or original.bot_id != envelope.bot_id
                or original.tenant_id != envelope.tenant_id
                or original.correlation_id != envelope.correlation_id
            ):
                raise AnswerConflict()
            await self.issuer.tenant_active(envelope.tenant_id)
            bot = await db.scalar(
                select(Bot)
                .where(
                    Bot.id == envelope.bot_id,
                    Bot.tenant_id == envelope.tenant_id,
                    Bot.is_active.is_(True),
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if bot is None:
                raise PlatformError(403)
            answer, created = await self.repo.admit(envelope, original.payload.chat_id)
            receipt = AnswerReceipt.model_validate(
                dict(
                    event_id=answer.event_id, delivery_id=answer.id, state=answer.state
                )
            )
            await db.commit()
            return receipt, created
        except Exception:
            await db.rollback()
            raise
