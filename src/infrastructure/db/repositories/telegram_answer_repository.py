from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.api.v1.schemas.telegram_answers import AnswerEnvelope
from src.infrastructure.db.models.telegram_answer import TelegramAnswerModel as Answer
from src.infrastructure.db.models.telegram_bot import TelegramBotModel as Bot
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


@dataclass(frozen=True)
class SendClaim:
    answer_id: UUID
    claim_id: UUID
    tenant_id: UUID
    bot_id: UUID
    chat_id: int
    text: str


class TelegramSendRepository:
    """Synchronous worker transactions; admission retains its async session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def now(self) -> datetime:
        return cast(
            datetime, self.session.execute(select(func.clock_timestamp())).scalar_one()
        )

    def claim(self, answer_id: UUID) -> SendClaim | None:
        candidate = self.session.scalar(
            select(Answer).where(
                Answer.id == answer_id,
                Answer.state == "pending",
                Answer.next_attempt_at <= func.clock_timestamp(),
            )
        )
        if candidate is None:
            return None
        # Admission and send-start lock the bot first as well.
        bot = self.session.scalar(
            select(Bot)
            .where(
                Bot.id == candidate.bot_id,
                Bot.tenant_id == candidate.tenant_id,
            )
            .with_for_update()
        )
        row = self.session.scalar(
            select(Answer)
            .where(
                Answer.id == answer_id,
                Answer.state == "pending",
                Answer.next_attempt_at <= func.clock_timestamp(),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        now = self.now()
        if bot is None or not bot.is_active:
            row.state, row.error_code, row.updated_at = (
                "cancelled",
                "inactive_context",
                now,
            )
            return None
        if row.send_started_at is not None or row.attempts >= 5:
            row.state = "unknown" if row.send_started_at is not None else "failed"
            row.error_code = "attempts_exhausted"
            row.updated_at = now
            return None
        row.state, row.claim_id = "processing", uuid4()
        row.claim_deadline = now + timedelta(seconds=60)
        row.attempts += 1
        row.updated_at, row.error_code = now, None
        return SendClaim(
            row.id, row.claim_id, row.tenant_id, row.bot_id, row.chat_id, row.text
        )

    def owned(self, claim: SendClaim) -> Answer | None:
        row = self.session.scalar(
            select(Answer)
            .where(
                Answer.id == claim.answer_id,
                Answer.tenant_id == claim.tenant_id,
                Answer.bot_id == claim.bot_id,
                Answer.claim_id == claim.claim_id,
                Answer.state == "processing",
                Answer.claim_deadline > func.clock_timestamp(),
            )
            .with_for_update()
        )
        if (
            row is not None
            and row.claim_deadline is not None
            and row.claim_deadline > self.now()
        ):
            return row
        return None

    def mark_started(self, claim: SendClaim) -> bool:
        row = self.owned(claim)
        if row is None or row.send_started_at is not None:
            return False
        row.send_started_at = self.now()
        row.updated_at = row.send_started_at
        return True

    def finish(
        self,
        claim: SendClaim,
        state: str,
        code: str | None,
        *,
        started: bool,
        message_id: int | None = None,
        retry_after: int = 0,
    ) -> bool:
        row = self.owned(claim)
        if row is None or (row.send_started_at is not None) != started:
            return False
        now = self.now()
        row.state = "failed" if state == "pending" and row.attempts >= 5 else state
        row.error_code, row.message_id = code, message_id
        row.next_attempt_at = now + timedelta(
            seconds=max(min(2**row.attempts, 60), min(retry_after, 3600))
        )
        if state == "pending" or (
            row.state == "failed" and code == "send_retry_exhausted"
        ):
            row.send_started_at = None
        row.claim_id, row.claim_deadline, row.updated_at = None, None, now
        return True

    def recover_due(self, batch_size: int = 100) -> list[UUID]:
        if not 1 <= batch_size <= 100:
            raise ValueError("Invalid scanner batch size")
        rows = self.session.scalars(
            select(Answer)
            .where(
                or_(
                    (Answer.state == "pending")
                    & (Answer.next_attempt_at <= func.clock_timestamp()),
                    (Answer.state == "processing")
                    & (Answer.claim_deadline <= func.clock_timestamp()),
                )
            )
            .order_by(Answer.next_attempt_at, Answer.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        now, due = self.now(), []
        for row in rows:
            if (
                row.state == "processing"
                or row.send_started_at is not None
                or row.attempts >= 5
            ):
                row.state = (
                    "unknown"
                    if row.send_started_at is not None
                    else "failed"
                    if row.attempts >= 5
                    else "pending"
                )
                row.error_code = "claim_expired"
                row.next_attempt_at = now + timedelta(seconds=min(2**row.attempts, 60))
                row.claim_id, row.claim_deadline, row.updated_at = None, None, now
            else:
                due.append(row.id)
        return due
