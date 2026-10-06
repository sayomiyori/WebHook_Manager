import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from src.api.main import app
from src.api.v1.dependencies.platform import get_issuer, get_platform_settings
from src.core.config import settings
from src.infrastructure.db.models.platform_ingress_outbox import (
    PlatformIngressOutboxModel,
)
from src.infrastructure.db.models.telegram_bot import TelegramBotModel
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel,
)
from src.infrastructure.platform.clients import AuthFortressClient

ROUTE = "/internal/v1/telegram/answers"
KEY = b"synthetic-answer-signature-key-32chars"


@pytest.fixture
async def answer_input(client, db_session):
    tenant, bot, ingress, correlation, job = [uuid4() for _ in range(5)]
    config = settings.model_copy(
        update={
            "PLATFORM_BOTS_ENABLED": True,
            "PLATFORM_TELEGRAM_ENABLED": True,
            "TELEGRAM_REPLIES_ENABLED": True,
            "AGENT_WEBHOOK_REPLY_KEY": SecretStr(KEY.decode()),
        }
    )
    state = {"active": True, "status": 200, "checks": 0}

    def issuer(request):
        state["checks"] += 1
        return httpx.Response(
            state["status"],
            json={
                "tenant_id": str(tenant),
                "is_active": state["active"],
            },
        )

    app.dependency_overrides[get_platform_settings] = lambda: config
    app.dependency_overrides[get_issuer] = lambda: AuthFortressClient(
        "http://auth_service:8000",
        SecretStr("synthetic-issuer-service-key-32chars"),
        transport=httpx.MockTransport(issuer),
    )
    db_session.add(
        TelegramBotModel(
            id=bot,
            tenant_id=tenant,
            created_by=uuid4(),
            name="Answer test",
            telegram_bot_id=uuid4().int % 2**50,
            credentials_encrypted="synthetic-ciphertext",
        )
    )
    await db_session.flush()
    original = dict(
        event_id=str(ingress),
        tenant_id=str(tenant),
        bot_id=str(bot),
        correlation_id=str(correlation),
        event_type="telegram.message.received",
        schema_version=1,
        occurred_at=datetime.now(UTC).isoformat(),
        idempotency_key=f"telegram:{bot}:1",
        payload=dict(
            update_id=1, chat_id=12345, message_id=2, question="Synthetic question"
        ),
    )
    event = TelegramIngressEventModel(
        id=ingress,
        tenant_id=tenant,
        bot_id=bot,
        update_id=1,
        raw={},
        digest="a" * 64,
        state="accepted",
        correlation_id=correlation,
        envelope=original,
    )
    db_session.add(event)
    await db_session.flush()
    outbox = PlatformIngressOutboxModel(
        id=uuid4(),
        ingress_id=ingress,
        tenant_id=tenant,
        bot_id=bot,
        state="published",
        published_job_id=job,
    )
    db_session.add(outbox)
    await db_session.commit()
    envelope = dict(
        event_id=str(uuid4()),
        tenant_id=str(tenant),
        bot_id=str(bot),
        correlation_id=str(correlation),
        event_type="telegram.answer.created",
        schema_version=1,
        occurred_at=datetime.now(UTC).isoformat(),
        idempotency_key=f"telegram-answer:{ingress}",
        payload=dict(
            ingress_event_id=str(ingress), job_id=str(job), text="Synthetic answer"
        ),
    )
    yield envelope, event, outbox, state, config


def signed(body):
    return {
        "Content-Type": "application/json",
        "X-Webhook-Signature": "sha256="
        + hmac.new(KEY, body, hashlib.sha256).hexdigest(),
    }


async def post(client, envelope):
    body = json.dumps(envelope).encode()
    return await client.post(ROUTE, content=body, headers=signed(body))


async def test_signed_answer_has_one_intent_and_canonical_destination(
    client, db_session, answer_input
):
    from src.infrastructure.db.models.telegram_answer import TelegramAnswerModel

    envelope, _, _, state, _ = answer_input
    first, replay = await post(client, envelope), await post(client, envelope)
    assert first.status_code == 202 and replay.status_code == 200
    assert first.json() == replay.json()
    assert set(first.json()) == {"event_id", "delivery_id", "state"}
    answer = await db_session.scalar(
        select(TelegramAnswerModel).where(
            TelegramAnswerModel.ingress_id == envelope["payload"]["ingress_event_id"]
        )
    )
    assert answer.chat_id == 12345 and answer.text == envelope["payload"]["text"]
    assert answer.state == "pending" and answer.send_started_at is None
    assert state["checks"] == 2
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(TelegramAnswerModel)
            .where(
                TelegramAnswerModel.ingress_id
                == envelope["payload"]["ingress_event_id"]
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "kind,status",
    [
        ("tenant", 404),
        ("bot", 404),
        ("ingress", 404),
        ("correlation", 409),
        ("job", 409),
        ("ignored", 404),
        ("unpublished", 409),
    ],
)
async def test_original_scope_and_publication_binding(
    client, db_session, answer_input, kind, status
):
    envelope, event, outbox, _, _ = answer_input
    if kind in {"tenant", "bot", "correlation"}:
        envelope[f"{kind}_id"] = str(uuid4())
    elif kind == "ingress":
        value = str(uuid4())
        envelope["payload"]["ingress_event_id"] = value
        envelope["idempotency_key"] = f"telegram-answer:{value}"
    elif kind == "job":
        envelope["payload"]["job_id"] = str(uuid4())
    elif kind == "ignored":
        event.state = "ignored"
    else:
        outbox.state = "pending"
        outbox.published_job_id = None
    await db_session.commit()
    response = await post(client, envelope)
    assert response.status_code == status
    if kind == "unpublished":
        assert response.json() == {"detail": "ingress_publication_not_ready"}


@pytest.mark.parametrize("kind", ["text", "event"])
async def test_conflicting_replay_is_terminal(client, answer_input, kind):
    envelope = answer_input[0]
    assert (await post(client, envelope)).status_code == 202
    if kind == "text":
        envelope["payload"]["text"] = "Different answer"
    else:
        envelope["event_id"] = str(uuid4())
    response = await post(client, envelope)
    assert response.status_code == 409
    assert response.json() == {"detail": "answer_conflict"}


@pytest.mark.parametrize(
    "kind,status", [("tenant", 403), ("bot", 403), ("issuer", 503)]
)
async def test_fresh_active_context_required_even_on_replay(
    client, db_session, answer_input, kind, status
):
    envelope, _, _, state, _ = answer_input
    assert (await post(client, envelope)).status_code == 202
    if kind == "tenant":
        state["active"] = False
    elif kind == "issuer":
        state["status"] = 503
    else:
        bot = await db_session.get(TelegramBotModel, envelope["bot_id"])
        bot.is_active = False
        await db_session.commit()
    assert (await post(client, envelope)).status_code == status


@pytest.mark.parametrize(
    "kind", ["chat", "token", "bool", "timezone", "empty", "surrogate", "nul", "extra"]
)
async def test_strict_schema_rejects_destination_and_invalid_text(
    client, answer_input, kind
):
    envelope = answer_input[0]
    if kind in {"chat", "token"}:
        envelope["payload"][f"{kind}_id" if kind == "chat" else "token"] = "forged"
    elif kind == "bool":
        envelope["schema_version"] = True
    elif kind == "timezone":
        envelope["occurred_at"] = "2026-10-06T03:00:00+03:00"
    elif kind == "extra":
        envelope["extra"] = "forged"
    else:
        envelope["payload"]["text"] = {
            "empty": " ",
            "surrogate": "\ud800",
            "nul": "a\x00b",
        }[kind]
    response = await post(client, envelope)
    assert response.status_code == 422 and "forged" not in response.text


async def test_signature_precedes_parse_and_duplicates_denied(client, answer_input):
    body = b"private-invalid-json"
    headers = signed(body)
    headers["X-Webhook-Signature"] = "sha256=" + "0" * 64
    assert (await client.post(ROUTE, content=body, headers=headers)).status_code == 401
    assert (
        await client.post(ROUTE, content=body, headers=list(signed(body).items()) * 2)
    ).status_code == 401
    for raw in (b'{"event_id":1,"event_id":2}', b'{"event_id":NaN}', body):
        response = await client.post(ROUTE, content=raw, headers=signed(raw))
        assert response.status_code == 422 and "private" not in response.text


async def test_stream_limits_encoding_and_disconnect(client, answer_input):
    from starlette.requests import ClientDisconnect

    body = json.dumps(answer_input[0]).encode()
    headers = signed(body)
    assert (
        await client.post(
            ROUTE, content=body, headers={**headers, "Content-Encoding": "gzip"}
        )
    ).status_code == 415
    padded = body + b" " * (1048576 - len(body))
    assert (
        await client.post(ROUTE, content=padded, headers=signed(padded))
    ).status_code == 202
    consumed = []

    async def chunks():
        consumed.append(1)
        yield b" " * 1048576
        consumed.append(2)
        yield b" "
        consumed.append(3)
        yield b"unread"

    assert (
        await client.post(ROUTE, content=chunks(), headers=headers)
    ).status_code == 413
    assert consumed == [1, 2]

    async def disconnected():
        yield b"partial"
        raise ClientDisconnect()

    assert (
        await client.post(ROUTE, content=disconnected(), headers=headers)
    ).status_code == 400


async def test_disabled_answer_endpoint_has_no_database_effect(client):
    response = await client.post(ROUTE, json={})
    assert response.status_code == 503


async def test_sql_commit_failure_rolls_back_intent(
    client, db_session, answer_input, monkeypatch
):
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import SQLAlchemyError

    from src.infrastructure.db.models.telegram_answer import TelegramAnswerModel

    monkeypatch.setattr(
        db_session,
        "commit",
        AsyncMock(side_effect=SQLAlchemyError("synthetic-private-db-error")),
    )
    response = await post(client, answer_input[0])
    assert response.status_code == 503 and "private" not in response.text
    assert (
        await db_session.scalar(
            select(TelegramAnswerModel.id).where(
                TelegramAnswerModel.event_id == answer_input[0]["event_id"]
            )
        )
        is None
    )


@pytest.mark.parametrize("conflicting", [False, True])
async def test_independent_concurrent_admission_has_one_receipt(
    answer_input, conflicting
):
    import asyncio
    from copy import deepcopy

    from src.api.v1.schemas.telegram_answers import AnswerEnvelope
    from src.infrastructure.db.base import async_session_maker
    from src.infrastructure.db.models.telegram_answer import TelegramAnswerModel
    from src.infrastructure.db.repositories.telegram_answer_repository import (
        AnswerConflict,
        TelegramAnswerRepository,
    )
    from src.services.telegram_answer_service import TelegramAnswerService

    envelope, source, publication, _, _ = answer_input
    envelope = deepcopy(envelope)
    bot, ingress = uuid4(), uuid4()
    envelope["bot_id"] = str(bot)
    envelope["payload"]["ingress_event_id"] = str(ingress)
    envelope["idempotency_key"] = f"telegram-answer:{ingress}"
    original = deepcopy(source.envelope)
    original["event_id"], original["bot_id"] = str(ingress), str(bot)
    original["idempotency_key"] = f"telegram:{bot}:1"
    async with async_session_maker() as db:
        db.add(
            TelegramBotModel(
                id=bot,
                tenant_id=source.tenant_id,
                created_by=uuid4(),
                name="Concurrent answer",
                telegram_bot_id=uuid4().int % 2**50,
                credentials_encrypted="synthetic-ciphertext",
            )
        )
        await db.flush()
        db.add(
            TelegramIngressEventModel(
                id=ingress,
                tenant_id=source.tenant_id,
                bot_id=bot,
                update_id=1,
                raw={},
                digest="a" * 64,
                state="accepted",
                correlation_id=source.correlation_id,
                envelope=original,
            )
        )
        await db.flush()
        db.add(
            PlatformIngressOutboxModel(
                id=uuid4(),
                ingress_id=ingress,
                tenant_id=source.tenant_id,
                bot_id=bot,
                state="published",
                published_job_id=publication.published_job_id,
            )
        )
        await db.commit()
    parsed = AnswerEnvelope.model_validate_json(json.dumps(envelope))

    async def admit(value=parsed):
        async with async_session_maker() as db:
            return await TelegramAnswerService(
                TelegramAnswerRepository(db), app.dependency_overrides[get_issuer]()
            ).admit(value)

    changed = deepcopy(envelope)
    changed["payload"]["text"] = "Concurrent conflicting answer"
    conflict = AnswerEnvelope.model_validate_json(json.dumps(changed))
    values = [parsed, conflict, parsed, conflict] if conflicting else [parsed] * 4
    results = await asyncio.gather(
        *[admit(value) for value in values], return_exceptions=True
    )
    assert sum(isinstance(result, AnswerConflict) for result in results) == (
        2 if conflicting else 0
    )
    accepted = [result for result in results if not isinstance(result, Exception)]
    assert sum(created for _, created in accepted) == 1
    assert len({receipt.delivery_id for receipt, _ in accepted}) == 1
    async with async_session_maker() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(TelegramAnswerModel)
                .where(TelegramAnswerModel.ingress_id == ingress)
            )
            == 1
        )


@pytest.mark.parametrize(
    "values",
    [
        {"tenant_id": "00000000-0000-0000-0000-000000000001"},
        {"state": "processing"},
        {"state": "succeeded"},
        {"attempts": 6},
    ],
)
async def test_answer_database_constraints_reject_invalid_scope_and_state(
    client, db_session, answer_input, values
):
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.db.models.telegram_answer import TelegramAnswerModel

    assert (await post(client, answer_input[0])).status_code == 202
    async with db_session.begin_nested() as transaction:
        with pytest.raises(IntegrityError):
            await db_session.execute(
                update(TelegramAnswerModel)
                .where(TelegramAnswerModel.event_id == answer_input[0]["event_id"])
                .values(**values)
            )
        await transaction.rollback()
