# ruff: noqa: F811
# Imported pytest fixtures intentionally share names with fixture parameters.
import asyncio
from uuid import UUID

import pytest
from sqlalchemy import func, select
from tests.e2e.test_platform_bots import base, create
from tests.e2e.test_telegram_provisioning import (
    registry_platform,  # noqa: F401
    telegram_platform,  # noqa: F401
)

from src.infrastructure.db.models.platform_ingress_outbox import (
    PlatformIngressOutboxModel,
)
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel,
)


@pytest.mark.parametrize("chat_type", [[], {}])
async def test_invalid_chat_type_is_sanitized_422(client, telegram_platform, chat_type):
    route, headers = await setup(client, telegram_platform)
    raw = payload()
    raw["message"]["chat"]["type"] = chat_type
    response = await client.post(route, headers=headers, json=raw)
    assert response.status_code == 422
    assert "chat" not in response.text and "forged" not in response.text


async def test_stream_limits_encoding_disconnect_and_duplicate_headers(
    client, db_session, telegram_platform
):
    import json

    from starlette.requests import ClientDisconnect

    route, headers = await setup(client, telegram_platform)
    repeated = list(headers.items()) * 2
    assert (
        await client.post(route, headers=repeated, content=b"bad")
    ).status_code == 401
    assert (
        await client.post(
            route, headers={**headers, "Content-Encoding": "gzip"}, json=payload()
        )
    ).status_code == 415
    raw = json.dumps(payload()).encode()
    assert (
        await client.post(
            route,
            headers={**headers, "Content-Type": "application/json"},
            content=raw + b" " * (1048576 - len(raw)),
        )
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
        await client.post(
            route,
            headers={**headers, "Content-Type": "application/json"},
            content=chunks(),
        )
    ).status_code == 413
    assert consumed == [1, 2]

    async def disconnected():
        yield b'{"update_id":123'
        raise ClientDisconnect()

    assert (
        await client.post(
            route,
            headers={**headers, "Content-Type": "application/json"},
            content=disconnected(),
        )
    ).status_code == 400
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(TelegramIngressEventModel)
            .where(TelegramIngressEventModel.tenant_id == telegram_platform["tenant"])
        )
        == 1
    )


def independent_ingress(telegram_platform):
    from pydantic import SecretStr
    from tests.integration.test_platform_publication import provision

    from src.api.main import app
    from src.core.dependencies import get_session
    from src.infrastructure.db.base import async_session_maker, sync_session_maker
    from src.infrastructure.db.models.telegram_bot_webhook import (
        TelegramBotWebhookModel,
    )
    from src.infrastructure.platform.webhook_credentials import WebhookCredentials

    outbox_id, envelope = provision()
    telegram_platform["tenant"] = envelope.tenant_id
    secret = SecretStr("fictional-prepared-webhook-secret")
    with sync_session_maker() as session:
        session.add(
            TelegramBotWebhookModel(
                bot_id=envelope.bot_id,
                tenant_id=envelope.tenant_id,
                state="configured",
                encrypted_secret="fictional-ciphertext",
                secret_digest=WebhookCredentials.digest(secret),
                url="https://demo.example.com/webhooks/telegram/"
                + str(envelope.bot_id),
            )
        )
        session.commit()

    async def independent_session():
        async with async_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = independent_session
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret.get_secret_value()}
    route = "/webhooks/telegram/" + str(envelope.bot_id)
    return route, headers, envelope, outbox_id


async def test_concurrent_identical_http_updates_use_one_event(
    client, telegram_platform
):
    from src.infrastructure.db.base import async_session_maker

    route, headers, _, _ = independent_ingress(telegram_platform)
    first, second = await asyncio.gather(
        client.post(route, headers=headers, json=payload()),
        client.post(route, headers=headers, json=payload()),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 202]
    assert first.json()["event_id"] == second.json()["event_id"]
    async with async_session_maker() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PlatformIngressOutboxModel)
                .where(
                    PlatformIngressOutboxModel.ingress_id
                    == UUID(first.json()["event_id"])
                )
            )
            == 1
        )


async def test_sql_failure_rolls_back_both_ingress_and_outbox(
    client, telegram_platform
):
    from sqlalchemy import event, text

    from src.infrastructure.db.base import async_session_maker, engine

    route, headers, envelope, outbox_id = independent_ingress(telegram_platform)
    injected = []

    def unique_violation(
        connection, cursor, statement, parameters, context, executemany
    ):
        if "INSERT INTO platform_ingress_outbox" in statement and not injected:
            injected.append(True)
            # A real PostgreSQL duplicate-key error at the SQL boundary, after
            # ingress INSERT and before the transaction can commit.
            connection.execute(
                text(
                    "INSERT INTO platform_ingress_outbox "
                    "SELECT * FROM platform_ingress_outbox WHERE id=:id"
                ),
                {"id": outbox_id},
            )

    event.listen(engine.sync_engine, "before_cursor_execute", unique_violation)
    try:
        response = await client.post(route, headers=headers, json=payload())
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", unique_violation)
    assert injected and response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
    async with async_session_maker() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TelegramIngressEventModel)
                .where(
                    TelegramIngressEventModel.bot_id == envelope.bot_id,
                    TelegramIngressEventModel.update_id == payload()["update_id"],
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PlatformIngressOutboxModel)
                .where(PlatformIngressOutboxModel.bot_id == envelope.bot_id)
            )
            == 1
        )


async def setup(client, state):
    bot = (await create(client, state)).json()
    result = await client.post(
        base(state) + "/" + bot["id"] + "/webhook",
        headers=state["headers"],
        json={"dry_run": False},
    )
    assert result.status_code == 200
    return "/webhooks/telegram/" + bot["id"], {
        "X-Telegram-Bot-Api-Secret-Token": state["setup_calls"][0]["secret_token"]
    }


def payload():
    return {
        "update_id": 19,
        "message": {
            "message_id": 7,
            "chat": {"id": 23, "type": "private"},
            "text": "Hello",
        },
        "tenant_id": "forged",
    }


async def test_admission_is_atomic_scoped_and_replay_safe(
    client, db_session, telegram_platform
):
    route, headers = await setup(client, telegram_platform)
    response = await client.post(route, headers=headers, json=payload())
    assert response.status_code == 202
    event_id = UUID(response.json()["event_id"])
    event = await db_session.get(TelegramIngressEventModel, event_id)
    assert event.tenant_id == telegram_platform["tenant"]
    assert event.envelope["payload"] == {
        "update_id": 19,
        "message_id": 7,
        "chat_id": 23,
        "question": "Hello",
    }
    assert event.envelope["tenant_id"] == str(telegram_platform["tenant"])
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(PlatformIngressOutboxModel)
            .where(PlatformIngressOutboxModel.tenant_id == telegram_platform["tenant"])
        )
        == 1
    )
    replay = await client.post(route, headers=headers, json=payload())
    assert replay.status_code == 200 and replay.json()["event_id"] == str(event_id)
    changed = payload()
    changed["message"]["text"] = "Changed"
    assert (await client.post(route, headers=headers, json=changed)).status_code == 409


async def test_ingress_checks_credentials_before_json_and_ignores_non_text(
    client, db_session, telegram_platform
):
    route, headers = await setup(client, telegram_platform)
    assert (await client.post(route, content=b"bad")).status_code == 401
    assert (
        await client.post(
            route, headers=headers, json={"update_id": 20, "callback_query": {}}
        )
    ).status_code == 200
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(PlatformIngressOutboxModel)
            .where(PlatformIngressOutboxModel.tenant_id == telegram_platform["tenant"])
        )
        == 0
    )
    assert (
        await client.post(route, headers=headers, content=b"bad")
    ).status_code == 415
    assert (
        await client.post(
            route,
            headers={**headers, "Content-Type": "application/json"},
            content=b'{"update_id":1,"update_id":2}',
        )
    ).status_code == 422
    assert (
        await client.post(route, headers=headers, json={"update_id": True})
    ).status_code == 422
    assert (
        await client.post(
            route,
            headers={**headers, "Content-Type": "application/json"},
            content=b" " * (1048576 + 1),
        )
    ).status_code == 413
