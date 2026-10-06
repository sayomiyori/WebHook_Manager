from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.telegram_answers import AnswerEnvelope
from src.infrastructure.db.models.telegram_answer import TelegramAnswerModel as Answer
from src.infrastructure.platform.telegram_update import canonical_digest


class AnswerConflict(Exception):
    pass


class IngressNotReady(Exception):
    pass


class TelegramAnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def admit(
        self, envelope: AnswerEnvelope, chat_id: int
    ) -> tuple[Answer, bool]:
        data = envelope.model_dump(mode="json")
        digest = canonical_digest(data)
        row = (
            await self.session.execute(
                insert(Answer)
                .values(
                    id=uuid4(),
                    event_id=envelope.event_id,
                    ingress_id=envelope.payload.ingress_event_id,
                    job_id=envelope.payload.job_id,
                    tenant_id=envelope.tenant_id,
                    bot_id=envelope.bot_id,
                    correlation_id=envelope.correlation_id,
                    envelope=data,
                    digest=digest,
                    chat_id=chat_id,
                    text=envelope.payload.text,
                )
                .on_conflict_do_nothing()
                .returning(Answer)
            )
        ).scalar_one_or_none()
        if row is not None:
            return row, True
        matches = list(
            (
                await self.session.scalars(
                    select(Answer).where(
                        Answer.tenant_id == envelope.tenant_id,
                        Answer.bot_id == envelope.bot_id,
                        or_(
                            Answer.event_id == envelope.event_id,
                            Answer.ingress_id == envelope.payload.ingress_event_id,
                        ),
                    )
                )
            ).all()
        )
        if (
            len(matches) != 1
            or matches[0].digest != digest
            or matches[0].chat_id != chat_id
        ):
            raise AnswerConflict()
        return matches[0], False
