from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from src.infrastructure.db.models.platform_ingress_outbox import (
    PlatformIngressOutboxModel as Outbox,
)
from src.infrastructure.platform.agent_admission import AdmissionReceipt


class PlatformOutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def due() -> ColumnElement[bool]:
        return or_(
            (Outbox.state == "pending")
            & (Outbox.next_attempt_at <= func.clock_timestamp()),
            (Outbox.state == "processing")
            & (Outbox.claim_deadline <= func.clock_timestamp()),
        )

    def due_ids(self, limit: int = 100) -> list[UUID]:
        return list(
            self.session.scalars(
                select(Outbox.id)
                .where(self.due())
                .order_by(Outbox.next_attempt_at, Outbox.id)
                .limit(min(limit, 100))
            )
        )

    def claim(self, outbox_id: UUID, max_attempts: int) -> Outbox | None:
        self.session.execute(
            update(Outbox)
            .where(Outbox.id == outbox_id, self.due(), Outbox.attempts >= max_attempts)
            .values(
                state="failed",
                error_code="admission_outcome_unconfirmed",
                claim_id=None,
                claim_deadline=None,
                updated_at=func.clock_timestamp(),
            )
        )
        now = self.session.execute(select(func.clock_timestamp())).scalar_one()
        row = self.session.execute(
            update(Outbox)
            .where(Outbox.id == outbox_id, self.due(), Outbox.attempts < max_attempts)
            .values(
                state="processing",
                claim_id=uuid4(),
                claim_deadline=now + timedelta(seconds=60),
                attempts=Outbox.attempts + 1,
                updated_at=now,
            )
            .returning(Outbox)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        return row

    def finish(
        self, outbox_id: UUID, claim_id: UUID, receipt: AdmissionReceipt
    ) -> bool:
        return self._change(
            outbox_id,
            claim_id,
            state="published",
            published_job_id=receipt.job_id,
            error_code=None,
        )

    def cancel(self, outbox_id: UUID, claim_id: UUID) -> bool:
        return self._change(
            outbox_id, claim_id, state="cancelled", error_code="inactive_context"
        )

    def fail(
        self,
        outbox_id: UUID,
        claim_id: UUID,
        code: str,
        terminal: bool,
        retry_after: int | None,
        max_attempts: int = 10,
    ) -> bool:
        row = self.session.get(Outbox, outbox_id, populate_existing=True)
        if row is None:
            return False
        exhausted = terminal or row.attempts >= max_attempts
        delay = min(2**row.attempts, 60)
        if retry_after is not None:
            delay = max(delay, retry_after)
        now = self.session.execute(select(func.clock_timestamp())).scalar_one()
        return self._change(
            outbox_id,
            claim_id,
            state="failed" if exhausted else "pending",
            error_code=code,
            next_attempt_at=now + timedelta(seconds=delay),
        )

    def _change(self, outbox_id: UUID, claim_id: UUID, **values: object) -> bool:
        return (
            self.session.scalar(
                update(Outbox)
                .where(
                    Outbox.id == outbox_id,
                    Outbox.state == "processing",
                    Outbox.claim_id == claim_id,
                    Outbox.claim_deadline > func.clock_timestamp(),
                )
                .values(
                    **values,
                    claim_id=None,
                    claim_deadline=None,
                    updated_at=func.clock_timestamp(),
                )
                .returning(Outbox.id)
            )
            is not None
        )
