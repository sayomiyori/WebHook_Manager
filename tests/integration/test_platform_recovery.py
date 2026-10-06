from scripts import recover_platform_outbox as recovery
from sqlalchemy import func, text, update
from tests.integration.test_platform_publication import provision
from tests.unit.test_telegram_configuration import configuration

from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.models.platform_ingress_outbox import (
    PlatformIngressOutboxModel as Outbox,
)


def test_broker_failure_preserves_due_intent_and_resume(monkeypatch):
    outbox_id, _ = provision()
    with sync_session_maker() as session:
        # Keep this retained test row first in a bounded scan regardless of
        # earlier verification runs in the same dedicated database.
        session.execute(
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(next_attempt_at=func.clock_timestamp() - text("interval '1 year'"))
        )
        session.commit()
    monkeypatch.setattr(recovery, "settings", configuration())

    def unavailable(identifier):
        raise ConnectionError("controlled test boundary")

    monkeypatch.setattr(recovery, "enqueue", unavailable)
    recovery.scan_once()
    with sync_session_maker() as session:
        row = session.get(Outbox, outbox_id)
        assert row.state == "pending" and row.attempts == 0
    submitted = []
    monkeypatch.setattr(recovery, "enqueue", submitted.append)
    recovery.scan_once()
    assert str(outbox_id) in submitted
    with sync_session_maker() as session:
        row = session.get(Outbox, outbox_id)
        assert row.state == "pending" and row.attempts == 0
