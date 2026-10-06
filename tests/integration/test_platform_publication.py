from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, text, update

from src.api.v1.schemas.telegram_ingress import (
    TelegramIngressEnvelope,
    TelegramMessagePayload,
)
from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.models.platform_ingress_outbox import (
    PlatformIngressOutboxModel as Outbox,
)
from src.infrastructure.db.models.telegram_bot import TelegramBotModel as Bot
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel as Event,
)
from src.infrastructure.db.repositories.platform_outbox_repository import (
    PlatformOutboxRepository,
)
from src.infrastructure.platform.agent_admission import (
    AdmissionReceipt,
    AgentAdmissionClient,
)
from src.infrastructure.platform.clients import AuthFortressClient
from src.infrastructure.queue.tasks import publish_platform_ingress as worker


def provision():
    bot, tenant, event_id, outbox_id = uuid4(), uuid4(), uuid4(), uuid4()
    envelope = TelegramIngressEnvelope(
        event_id=event_id,
        bot_id=bot,
        tenant_id=tenant,
        occurred_at=datetime.now(UTC),
        correlation_id=uuid4(),
        idempotency_key=f"telegram:{bot}:1",
        payload=TelegramMessagePayload(
            update_id=1, message_id=1, chat_id=7, question="Hello"
        ),
    )
    with sync_session_maker() as session:
        session.add(
            Bot(
                id=bot,
                tenant_id=tenant,
                created_by=uuid4(),
                name="Publication test",
                telegram_bot_id=uuid4().int % 2**50,
                credentials_encrypted="fictional-ciphertext",
            )
        )
        session.flush()
        session.add(
            Event(
                id=event_id,
                bot_id=bot,
                tenant_id=tenant,
                update_id=1,
                raw={"update_id": 1},
                digest="a" * 64,
                state="accepted",
                correlation_id=envelope.correlation_id,
                envelope=envelope.model_dump(mode="json"),
            )
        )
        session.flush()
        session.add(
            Outbox(id=outbox_id, ingress_id=event_id, bot_id=bot, tenant_id=tenant)
        )
        session.commit()
    return outbox_id, envelope


def test_live_claim_and_expired_claim_fencing():
    outbox_id, event = provision()
    with sync_session_maker() as session:
        repo = PlatformOutboxRepository(session)
        first = repo.claim(outbox_id, 10)
        first_claim = first.claim_id
        session.commit()
        assert repo.claim(outbox_id, 10) is None
        session.commit()
        session.execute(
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(claim_deadline=func.clock_timestamp() - text("interval '1 second'"))
        )
        session.commit()
        second = repo.claim(outbox_id, 10)
        second_claim = second.claim_id
        session.commit()
        receipt = AdmissionReceipt(
            event_id=event.event_id, job_id=uuid4(), state="pending"
        )
        assert not repo.finish(outbox_id, first_claim, receipt)
        assert repo.finish(outbox_id, second_claim, receipt)
        session.commit()
        assert (
            session.get(Outbox, outbox_id, populate_existing=True).state == "published"
        )


def test_last_expired_claim_does_not_start_an_extra_attempt():
    outbox_id, _ = provision()
    with sync_session_maker() as session:
        session.execute(
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(
                state="processing",
                attempts=10,
                claim_id=uuid4(),
                claim_deadline=func.clock_timestamp() - text("interval '1 second'"),
            )
        )
        session.commit()
        assert PlatformOutboxRepository(session).claim(outbox_id, 10) is None
        session.commit()
        row = session.get(Outbox, outbox_id, populate_existing=True)
        assert row.state == "failed" and row.attempts == 10
        assert row.error_code == "admission_outcome_unconfirmed"


@pytest.fixture
def publication_http(monkeypatch):
    config = worker.settings.model_copy(
        update={
            "AUTHFORTRESS_BASE_URL": "http://auth_service:8000",
            "AUTHFORTRESS_WEBHOOK_SERVICE_KEY": SecretStr(
                "fictional-issuer-key-with-at-least-32-bytes"
            ),
            "AGENTHUB_BASE_URL": "http://agent_service:8000",
            "WEBHOOK_AGENT_INGRESS_KEY": SecretStr(
                "fictional-ingress-key-with-at-least-32-bytes"
            ),
            "PLATFORM_PUBLICATION_MAX_ATTEMPTS": 3,
        }
    )
    state = {
        "active": True,
        "issuer_status": 200,
        "agent_status": 202,
        "calls": [],
        "jobs": {},
        "expire_claim_on_receipt": False,
    }

    def issuer(request):
        return httpx.Response(
            state["issuer_status"],
            json={
                "tenant_id": request.url.path.split("/")[-2],
                "is_active": state["active"],
            },
        )

    def agent(request):
        import json

        from src.core.security import hmac_sha256_hex

        body = json.loads(request.content)
        assert request.headers["X-Webhook-Signature"] == "sha256=" + hmac_sha256_hex(
            secret=config.WEBHOOK_AGENT_INGRESS_KEY.get_secret_value(),
            message=request.content,
        )
        assert "authorization" not in request.headers
        state["calls"].append(body)
        job = state["jobs"].setdefault(body["event_id"], str(uuid4()))
        if state["expire_claim_on_receipt"]:
            with sync_session_maker() as session:
                session.execute(
                    update(Outbox)
                    .where(Outbox.ingress_id == UUID(body["event_id"]))
                    .values(
                        claim_deadline=func.clock_timestamp()
                        - text("interval '1 second'")
                    )
                )
                session.commit()
        return httpx.Response(
            state["agent_status"],
            json={"event_id": body["event_id"], "job_id": job, "state": "pending"},
        )

    monkeypatch.setattr(worker, "settings", config)
    monkeypatch.setattr(
        worker,
        "AuthFortressClient",
        lambda url, key: AuthFortressClient(
            url, key, transport=httpx.MockTransport(issuer)
        ),
    )
    monkeypatch.setattr(
        worker,
        "AgentAdmissionClient",
        lambda settings: AgentAdmissionClient(
            settings, transport=httpx.MockTransport(agent)
        ),
    )
    return state


def test_worker_replays_lost_receipt_without_duplicate_job(publication_http):
    state = publication_http
    outbox_id, envelope = provision()
    state["agent_status"] = 500
    assert worker._publish(outbox_id) == {"status": "deferred"}
    with sync_session_maker() as session:
        row = session.get(Outbox, outbox_id)
        assert row.state == "pending" and row.attempts == 1
        assert row.next_attempt_at > session.scalar(text("SELECT clock_timestamp()"))
        session.execute(
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(next_attempt_at=func.clock_timestamp())
        )
        session.commit()
    state["agent_status"] = 200
    assert worker._publish(outbox_id) == {"status": "published"}
    assert worker._publish(outbox_id) == {"status": "not_claimed"}
    assert len(state["calls"]) == 2 and len(state["jobs"]) == 1
    with sync_session_maker() as session:
        row = session.get(Outbox, outbox_id)
        assert row.attempts == 2
        assert str(row.published_job_id) == state["jobs"][str(envelope.event_id)]


def test_independent_concurrent_claims_have_one_winner():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    outbox_id, _ = provision()
    barrier = Barrier(2)

    def claim():
        with sync_session_maker() as session:
            barrier.wait(timeout=5)
            row = PlatformOutboxRepository(session).claim(outbox_id, 3)
            session.commit()
            return row is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == [False, True]


def test_remote_acceptance_after_expired_claim_is_recovered_with_one_job(
    publication_http,
):
    state = publication_http
    outbox_id, _ = provision()
    state["expire_claim_on_receipt"] = True
    assert worker._publish(outbox_id) == {"status": "stale_claim"}
    with sync_session_maker() as session:
        assert session.get(Outbox, outbox_id).state == "processing"
    state["expire_claim_on_receipt"] = False
    assert worker._publish(outbox_id) == {"status": "published"}
    assert len(state["calls"]) == 2 and len(state["jobs"]) == 1


@pytest.mark.parametrize(
    "outcome",
    [
        "inactive_tenant",
        "inactive_bot",
        "issuer_outage",
        "terminal",
        "invalid_envelope",
    ],
)
def test_worker_failure_paths_are_persisted(outcome, publication_http):
    state = publication_http
    outbox_id, envelope = provision()
    expected = "failed"
    if outcome == "inactive_tenant":
        state["active"] = False
        expected = "cancelled"
    elif outcome == "inactive_bot":
        with sync_session_maker() as session:
            session.execute(
                update(Bot).where(Bot.id == envelope.bot_id).values(is_active=False)
            )
            session.commit()
        expected = "cancelled"
    elif outcome == "issuer_outage":
        state["issuer_status"] = 503
        expected = "pending"
    elif outcome == "terminal":
        state["agent_status"] = 422
    else:
        with sync_session_maker() as session:
            session.execute(
                update(Event).where(Event.id == envelope.event_id).values(envelope={})
            )
            session.commit()
    worker._publish(outbox_id)
    with sync_session_maker() as session:
        row = session.get(Outbox, outbox_id)
        assert row.state == expected and row.attempts == 1
    assert len(state["calls"]) == (1 if outcome == "terminal" else 0)
