import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import func, text, update

from src.core.config import settings
from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.models.telegram_answer import TelegramAnswerModel as Answer
from src.infrastructure.db.models.telegram_bot import TelegramBotModel as Bot
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel as Ingress,
)
from src.infrastructure.platform.credentials import BotCredentials

TOKEN = "123456:synthetic_SEND-test-token"


@pytest.fixture
def send_input(monkeypatch):
    tenant, bot, ingress, answer = [uuid4() for _ in range(4)]
    key = SecretStr(Fernet.generate_key().decode())
    config = settings.model_copy(
        update={
            "TELEGRAM_REPLIES_ENABLED": True,
            "AUTHFORTRESS_BASE_URL": "http://auth_service:8000",
            "BOT_CREDENTIALS_KEY": key,
            "AUTHFORTRESS_WEBHOOK_SERVICE_KEY": SecretStr("a" * 32),
        }
    )
    original = dict(
        event_id=str(ingress),
        tenant_id=str(tenant),
        bot_id=str(bot),
        correlation_id=str(uuid4()),
        event_type="telegram.message.received",
        schema_version=1,
        occurred_at=datetime.now(UTC).isoformat(),
        idempotency_key=f"telegram:{bot}:1",
        payload=dict(update_id=1, chat_id=7, message_id=2, question="Question"),
    )
    envelope = dict(
        event_id=str(uuid4()),
        tenant_id=str(tenant),
        bot_id=str(bot),
        correlation_id=original["correlation_id"],
        event_type="telegram.answer.created",
        schema_version=1,
        occurred_at=datetime.now(UTC).isoformat(),
        idempotency_key=f"telegram-answer:{ingress}",
        payload=dict(
            ingress_event_id=str(ingress), job_id=str(uuid4()), text="Plain <answer>"
        ),
    )
    with sync_session_maker() as db:
        db.add(
            Bot(
                id=bot,
                tenant_id=tenant,
                created_by=uuid4(),
                name="Sender test",
                telegram_bot_id=uuid4().int % 2**50,
                credentials_encrypted=BotCredentials(key).encrypt(
                    bot, tenant, SecretStr(TOKEN)
                ),
            )
        )
        db.flush()
        db.add(
            Ingress(
                id=ingress,
                tenant_id=tenant,
                bot_id=bot,
                update_id=1,
                raw={},
                digest="a" * 64,
                state="accepted",
                correlation_id=original["correlation_id"],
                envelope=original,
            )
        )
        db.flush()
        db.add(
            Answer(
                id=answer,
                event_id=envelope["event_id"],
                tenant_id=tenant,
                bot_id=bot,
                ingress_id=ingress,
                job_id=envelope["payload"]["job_id"],
                correlation_id=original["correlation_id"],
                envelope=envelope,
                digest="b" * 64,
                chat_id=7,
                text="Plain <answer>",
            )
        )
        db.commit()
    state = {"calls": 0, "status": 200, "active": True}

    def handler(request):
        if request.url.host == "auth_service":
            return httpx.Response(
                200, json=dict(tenant_id=str(tenant), is_active=state["active"])
            )
        assert str(request.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        assert json.loads(request.content) == {"chat_id": 7, "text": "Plain <answer>"}
        state["calls"] += 1
        with sync_session_maker() as db:
            row = db.get(Answer, answer)
            assert row.state == "processing" and row.send_started_at is not None
        if state.get("timeout"):
            raise httpx.ReadTimeout(TOKEN)
        if "raw" in state:
            return httpx.Response(
                state["status"],
                headers={
                    "Content-Type": "application/json",
                    **state.get("headers", {}),
                },
                stream=httpx.ByteStream(state["raw"]),
            )
        return httpx.Response(
            state["status"],
            json=state.get(
                "body", {"ok": True, "result": {"message_id": 31, "chat": {"id": 7}}}
            ),
        )

    original_client = httpx.AsyncClient

    class Client(original_client):
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    yield answer, bot, config, state


def run(send_input, monkeypatch):
    from src.infrastructure.queue.tasks import send_telegram_answer as worker

    monkeypatch.setattr(worker, "settings", send_input[2])
    worker.send_telegram_answer.run(str(send_input[0]))


def row(answer):
    with sync_session_maker() as db:
        return db.get(Answer, answer)


def due(answer):
    with sync_session_maker() as db:
        db.execute(
            update(Answer)
            .where(Answer.id == answer)
            .values(
                next_attempt_at=func.clock_timestamp() - text("interval '1 second'")
            )
        )
        db.commit()


def test_confirmed_success_duplicate_does_not_send_again(send_input, monkeypatch):
    run(send_input, monkeypatch)
    run(send_input, monkeypatch)
    result = row(send_input[0])
    assert (
        result.state == "succeeded" and result.message_id == 31 and result.attempts == 1
    )
    assert send_input[3]["calls"] == 1


@pytest.mark.parametrize(
    "kind", ["timeout", "malformed", "wrong_chat", "boolean_id", "quota_ambiguous"]
)
def test_ambiguous_effect_never_retries(send_input, monkeypatch, kind, caplog):
    state = send_input[3]
    if kind == "timeout":
        state["timeout"] = True
    elif kind == "quota_ambiguous":
        state.update(status=429, body={"ok": False, "error_code": 429})
    else:
        state["body"] = (
            {
                "ok": True,
                "result": {
                    "message_id": True if kind == "boolean_id" else 31,
                    "chat": {"id": 8 if kind == "wrong_chat" else 7},
                },
            }
            if kind != "malformed"
            else {"ok": True}
        )
    run(send_input, monkeypatch)
    due(send_input[0])
    run(send_input, monkeypatch)
    assert row(send_input[0]).state == "unknown" and state["calls"] == 1
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_confirmed_permanent_rejection_stops(send_input, monkeypatch, status):
    send_input[3].update(status=status, body={"ok": False, "error_code": status})
    run(send_input, monkeypatch)
    run(send_input, monkeypatch)
    assert row(send_input[0]).state == "failed" and send_input[3]["calls"] == 1


def test_confirmed_retry_after_is_bounded_and_max_five(send_input, monkeypatch):
    send_input[3].update(
        status=429,
        body={"ok": False, "error_code": 429, "parameters": {"retry_after": 999999}},
    )
    for attempt in range(1, 6):
        run(send_input, monkeypatch)
        result = row(send_input[0])
        assert result.attempts == attempt and result.send_started_at is None
        assert result.state == ("failed" if attempt == 5 else "pending")
        assert (
            3599 <= (result.next_attempt_at - result.updated_at).total_seconds() <= 3600
        )
        due(send_input[0])
    run(send_input, monkeypatch)
    assert send_input[3]["calls"] == 5


@pytest.mark.parametrize("started,expected", [(False, "pending"), (True, "unknown")])
def test_expired_claim_before_after_marker(send_input, started, expected):
    from src.infrastructure.db.repositories.telegram_answer_repository import (
        TelegramSendRepository,
    )

    with sync_session_maker() as db:
        repo = TelegramSendRepository(db)
        claim = repo.claim(send_input[0])
        db.commit()
        if started:
            assert repo.mark_started(claim)
            db.commit()
        db.execute(
            update(Answer)
            .where(Answer.id == send_input[0])
            .values(claim_deadline=func.clock_timestamp() - text("interval '1 second'"))
        )
        db.commit()
    with sync_session_maker() as db:
        TelegramSendRepository(db).recover_due()
        db.commit()
    assert row(send_input[0]).state == expected


@pytest.mark.parametrize("kind", ["tenant", "bot"])
def test_deactivation_prevents_send(send_input, monkeypatch, kind):
    if kind == "tenant":
        send_input[3]["active"] = False
    else:
        with sync_session_maker() as db:
            db.execute(
                update(Bot).where(Bot.id == send_input[1]).values(is_active=False)
            )
            db.commit()
    run(send_input, monkeypatch)
    assert row(send_input[0]).state == "cancelled" and send_input[3]["calls"] == 0
    if kind == "bot":
        assert row(send_input[0]).attempts == 0


def test_concurrent_notifications_have_one_live_claim(send_input):
    from src.infrastructure.db.repositories.telegram_answer_repository import (
        TelegramSendRepository,
    )

    def acquire():
        with sync_session_maker() as db:
            claim = TelegramSendRepository(db).claim(send_input[0])
            db.commit()
            return claim

    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: acquire(), range(4)))
    assert sum(claim is not None for claim in claims) == 1
    assert row(send_input[0]).attempts == 1


@pytest.mark.parametrize("status", [500, 502, 503])
def test_confirmed_server_rejection_can_retry(send_input, monkeypatch, status):
    send_input[3].update(status=status, body={"ok": False, "error_code": status})
    run(send_input, monkeypatch)
    assert (
        row(send_input[0]).state == "pending"
        and row(send_input[0]).send_started_at is None
    )
    due(send_input[0])
    send_input[3]["status"] = 200
    send_input[3].pop("body")
    run(send_input, monkeypatch)
    assert row(send_input[0]).state == "succeeded" and send_input[3]["calls"] == 2


@pytest.mark.parametrize(
    "kind",
    [
        "server_ambiguous",
        "duplicate",
        "nan",
        "large",
        "encoding",
        "mime",
        "boolean_retry",
    ],
)
def test_invalid_remote_response_is_unknown(send_input, monkeypatch, kind):
    state = send_input[3]
    if kind == "server_ambiguous":
        state.update(status=503, raw=b"gateway unavailable")
    elif kind == "duplicate":
        state["raw"] = b'{"ok":true,"ok":false}'
    elif kind == "nan":
        state["raw"] = b'{"ok":NaN}'
    elif kind == "large":
        state["raw"] = b" " * 65537
    elif kind in {"encoding", "mime"}:
        state.update(
            raw=b"{}",
            headers={"Content-Encoding": "gzip"}
            if kind == "encoding"
            else {"Content-Type": "text/plain"},
        )
    else:
        state.update(
            status=429,
            body={"ok": False, "error_code": 429, "parameters": {"retry_after": True}},
        )
    run(send_input, monkeypatch)
    assert row(send_input[0]).state == "unknown"


@pytest.mark.parametrize("committed", [False, True])
def test_lost_success_persistence_never_repeats_effect(
    send_input, monkeypatch, committed
):
    from sqlalchemy.exc import SQLAlchemyError

    from src.infrastructure.db.repositories.telegram_answer_repository import (
        TelegramSendRepository,
    )
    from src.infrastructure.queue.tasks import send_telegram_answer as worker

    count = 0

    def factory():
        nonlocal count
        db = sync_session_maker()
        count += 1
        if count == 3:
            original = db.commit

            def commit():
                if committed:
                    original()
                raise SQLAlchemyError("Synthetic lost success receipt")

            db.commit = commit
        return db

    monkeypatch.setattr(worker, "sync_session_maker", factory)
    run(send_input, monkeypatch)
    if not committed:
        with sync_session_maker() as db:
            db.execute(
                update(Answer)
                .where(Answer.id == send_input[0])
                .values(
                    claim_deadline=func.clock_timestamp() - text("interval '1 second'")
                )
            )
            db.commit()
            TelegramSendRepository(db).recover_due()
            db.commit()
    run(send_input, monkeypatch)
    assert row(send_input[0]).state == ("succeeded" if committed else "unknown")
    assert send_input[3]["calls"] == 1


def test_marker_commit_receipt_loss_is_unknown_without_sending(send_input, monkeypatch):
    from src.infrastructure.db.repositories.telegram_answer_repository import (
        TelegramSendRepository,
    )
    from src.infrastructure.queue.tasks import send_telegram_answer as worker

    count = 0

    def factory():
        nonlocal count
        db = sync_session_maker()
        count += 1
        if count == 2:
            original = db.commit

            def commit():
                original()
                raise OSError("Synthetic marker receipt loss")

            db.commit = commit
        return db

    monkeypatch.setattr(worker, "sync_session_maker", factory)
    run(send_input, monkeypatch)
    assert (
        row(send_input[0]).state == "processing"
        and row(send_input[0]).send_started_at is not None
    )
    with sync_session_maker() as db:
        db.execute(
            update(Answer)
            .where(Answer.id == send_input[0])
            .values(claim_deadline=func.clock_timestamp() - text("interval '1 second'"))
        )
        db.commit()
        TelegramSendRepository(db).recover_due()
        db.commit()
    run(send_input, monkeypatch)
    assert row(send_input[0]).state == "unknown" and send_input[3]["calls"] == 0


def test_stale_claim_cannot_mark_or_overwrite(send_input):
    from src.infrastructure.db.repositories.telegram_answer_repository import (
        TelegramSendRepository,
    )

    with sync_session_maker() as db:
        repo = TelegramSendRepository(db)
        old = repo.claim(send_input[0])
        db.commit()
        db.execute(
            update(Answer)
            .where(Answer.id == send_input[0])
            .values(claim_deadline=func.clock_timestamp() - text("interval '1 second'"))
        )
        db.commit()
        repo.recover_due()
        db.commit()
    due(send_input[0])
    with sync_session_maker() as db:
        repo = TelegramSendRepository(db)
        current = repo.claim(send_input[0])
        db.commit()
        assert repo.mark_started(current)
        db.commit()
        assert repo.finish(current, "succeeded", None, started=True, message_id=31)
        db.commit()
        assert not repo.mark_started(old)
        assert not repo.finish(old, "failed", "stale", started=False)
    assert row(send_input[0]).state == "succeeded"


@pytest.mark.parametrize("identity", ["invalid", "", None, 123])
def test_malformed_uuid_notification_has_no_database_access(monkeypatch, identity):
    from src.infrastructure.queue.tasks import send_telegram_answer as worker

    monkeypatch.setattr(
        worker,
        "settings",
        settings.model_copy(update={"TELEGRAM_REPLIES_ENABLED": True}),
    )

    def forbidden():
        raise AssertionError("Invalid notification opened DB")

    monkeypatch.setattr(worker, "sync_session_maker", forbidden)
    worker.send_telegram_answer.run(identity)


def test_total_send_deadline_is_twenty_seconds(send_input, monkeypatch):
    original_timeout = asyncio.timeout
    deadlines = []

    def shorter(seconds):
        deadlines.append(seconds)
        return original_timeout(0.02 if seconds == 20 else seconds)

    async def handler(request):
        if request.url.host == "auth_service":
            with sync_session_maker() as db:
                tenant = str(db.get(Answer, send_input[0]).tenant_id)
            return httpx.Response(200, json={"tenant_id": tenant, "is_active": True})
        send_input[3]["calls"] += 1
        await asyncio.sleep(1)
        raise AssertionError("Send deadline failed")

    original_client = httpx.AsyncClient.__bases__[0]

    class Client(original_client):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr(asyncio, "timeout", shorter)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    run(send_input, monkeypatch)
    assert deadlines == [10, 20] and row(send_input[0]).state == "unknown"


def test_scanner_stops_on_real_broker_failure_and_can_resume(send_input, monkeypatch):
    from scripts import recover_telegram_answers as scanner

    monkeypatch.setattr(scanner, "settings", send_input[2])
    original = scanner.celery_app.conf.broker_url
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://127.0.0.1:1/0")
    try:
        assert scanner.recover_answers_once(1) == 0
    finally:
        monkeypatch.setenv("CELERY_BROKER_URL", original)
    ids = []
    monkeypatch.setattr(scanner, "enqueue", ids.append)
    assert scanner.recover_answers_once(1) == 1
    assert len(ids) == 1 and len(ids[0]) == 36


@pytest.mark.parametrize("batch", [0, 101])
def test_scanner_batch_bounded(send_input, monkeypatch, batch):
    from scripts import recover_telegram_answers as scanner

    monkeypatch.setattr(scanner, "settings", send_input[2])
    with pytest.raises(ValueError, match="batch"):
        scanner.recover_answers_once(batch)


def test_disabled_task_and_scanner_do_not_open_sessions(monkeypatch):
    from scripts import recover_telegram_answers as scanner

    from src.infrastructure.queue.tasks import send_telegram_answer as worker

    disabled = settings.model_copy(update={"TELEGRAM_REPLIES_ENABLED": False})
    monkeypatch.setattr(worker, "settings", disabled)
    monkeypatch.setattr(scanner, "settings", disabled)

    def forbidden():
        raise AssertionError("Disabled delivery opened DB")

    monkeypatch.setattr(worker, "sync_session_maker", forbidden)
    monkeypatch.setattr(scanner, "sync_session_maker", forbidden)
    worker.send_telegram_answer.run(str(uuid4()))
    assert scanner.recover_answers_once() == 0
