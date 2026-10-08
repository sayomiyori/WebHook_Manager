# ruff: noqa: F811
# Imported pytest fixtures intentionally share names with fixture parameters.
import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, text, update
from tests.e2e.test_platform_bots import base, create
from tests.e2e.test_platform_bots import platform as registry_platform  # noqa: F401

from src.api.main import app
from src.api.v1.dependencies.platform import get_platform_settings, get_telegram
from src.infrastructure.db.models.telegram_bot_webhook import TelegramBotWebhookModel
from src.infrastructure.platform.clients import TelegramClient
from src.infrastructure.platform.webhook_credentials import WebhookCredentials


@pytest.fixture
def telegram_platform(registry_platform):
    state = registry_platform
    original = app.dependency_overrides[get_platform_settings]()
    configured = original.model_copy(
        update={
            "PLATFORM_TELEGRAM_ENABLED": True,
            "TELEGRAM_WEBHOOK_ORIGIN": "https://demo.example.com",
            "AGENTHUB_BASE_URL": "http://agent_service:8000",
            "WEBHOOK_AGENT_INGRESS_KEY": SecretStr(
                "fictional-ingress-key-at-least-32-bytes"
            ),
        }
    )
    app.dependency_overrides[get_platform_settings] = lambda: configured
    state["setup_calls"] = []
    state["setup_status"] = 200
    state["setup_result"] = True

    def reply(request):
        if request.url.path.endswith("/setWebhook"):
            state["setup_calls"].append(json.loads(request.content))
            return httpx.Response(
                state["setup_status"],
                json=(
                    {"ok": False, "error_code": 400}
                    if state["setup_status"] == 400
                    else {"ok": True, "result": state["setup_result"]}
                ),
            )
        return httpx.Response(
            200,
            json={"ok": True, "result": {"id": state["telegram_id"], "is_bot": True}},
        )

    app.dependency_overrides[get_telegram] = lambda: TelegramClient(
        transport=httpx.MockTransport(reply)
    )
    return state


async def test_webhook_dry_run_has_no_side_effects(
    client, db_session, telegram_platform
):
    state = telegram_platform
    bot = (await create(client, state)).json()
    route = base(state) + "/" + bot["id"] + "/webhook"
    response = await client.post(
        route, headers=state["headers"], json={"dry_run": True}
    )
    assert response.status_code == 200
    assert response.json()["webhook_url"].endswith("/webhooks/telegram/" + bot["id"])
    assert state["setup_calls"] == []
    assert await db_session.get(TelegramBotWebhookModel, UUID(bot["id"])) is None
    state["role"] = "member"
    assert (
        await client.post(route, headers=state["headers"], json={"dry_run": False})
    ).status_code == 403


async def test_webhook_apply_persists_secret_and_is_idempotent(
    client, db_session, telegram_platform
):
    state = telegram_platform
    bot = (await create(client, state)).json()
    route = base(state) + "/" + bot["id"] + "/webhook"
    response = await client.post(
        route, headers=state["headers"], json={"dry_run": False}
    )
    assert response.status_code == 200
    assert response.json()["webhook_status"] == "configured"
    setup = state["setup_calls"][0]
    assert setup["drop_pending_updates"] is False and setup["allowed_updates"] == [
        "message"
    ]
    assert setup["max_connections"] == 10
    assert setup["secret_token"] not in response.text
    row = await db_session.get(TelegramBotWebhookModel, UUID(bot["id"]))
    assert setup["secret_token"] not in row.encrypted_secret
    assert row.tenant_id == state["tenant"] and row.claim_id is None
    assert (
        await client.post(route, headers=state["headers"], json={"dry_run": False})
    ).status_code == 200
    assert len(state["setup_calls"]) == 1
    assert (
        await client.get(base(state) + "/" + bot["id"], headers=state["headers"])
    ).json()["webhook_status"] == "configured"
    assert (
        await client.post(
            base(state) + "/" + str(uuid4()) + "/webhook",
            headers=state["headers"],
            json={"dry_run": True},
        )
    ).status_code == 404


async def test_unknown_setup_retry_reuses_prepared_secret(client, telegram_platform):
    state = telegram_platform
    bot = (await create(client, state)).json()
    route = base(state) + "/" + bot["id"] + "/webhook"
    state["setup_status"] = 500
    assert (
        await client.post(route, headers=state["headers"], json={"dry_run": False})
    ).status_code == 503
    original = app.dependency_overrides[get_platform_settings]()
    app.dependency_overrides[get_platform_settings] = lambda: original.model_copy(
        update={"TELEGRAM_WEBHOOK_ORIGIN": "https://new.example.com"}
    )
    dry_run = await client.post(route, headers=state["headers"], json={"dry_run": True})
    assert dry_run.json()["webhook_url"] == state["setup_calls"][0]["url"]
    state["setup_status"] = 200
    applied = await client.post(
        route, headers=state["headers"], json={"dry_run": False}
    )
    assert applied.status_code == 200
    assert applied.json()["webhook_url"] == state["setup_calls"][1]["url"]
    assert state["setup_calls"][0] == state["setup_calls"][1]


async def test_interrupted_expired_setup_is_reported_unknown(
    client, db_session, telegram_platform
):
    state = telegram_platform
    bot = (await create(client, state)).json()
    route = base(state) + "/" + bot["id"]
    state["setup_status"] = 500
    await client.post(
        route + "/webhook", headers=state["headers"], json={"dry_run": False}
    )
    await db_session.execute(
        update(TelegramBotWebhookModel)
        .where(TelegramBotWebhookModel.bot_id == UUID(bot["id"]))
        .values(
            state="configuring",
            claim_id=uuid4(),
            claim_deadline=func.clock_timestamp() - text("interval '1 second'"),
        )
    )
    await db_session.commit()
    result = await client.get(route, headers=state["headers"])
    assert result.status_code == 200
    assert result.json()["webhook_status"] == "unknown"


async def test_revoked_owner_releases_claim_before_provider(
    client, db_session, telegram_platform
):
    state = telegram_platform
    bot = (await create(client, state)).json()
    state["authorize_calls"] = 0
    state["revoke_after_provider"] = True
    response = await client.post(
        base(state) + "/" + bot["id"] + "/webhook",
        headers=state["headers"],
        json={"dry_run": False},
    )
    assert response.status_code == 401
    assert state["setup_calls"] == []
    row = await db_session.get(
        TelegramBotWebhookModel, UUID(bot["id"]), populate_existing=True
    )
    assert row.state == "failed" and row.claim_id is None


@pytest.mark.parametrize("replace_url", [False, True])
async def test_concurrent_setup_makes_one_provider_call(
    client, telegram_platform, replace_url
):
    from tests.integration.test_platform_publication import provision

    from src.core.dependencies import get_session
    from src.infrastructure.db.base import async_session_maker, sync_session_maker
    from src.infrastructure.db.models.telegram_bot import TelegramBotModel
    from src.infrastructure.platform.credentials import BotCredentials

    _, envelope = provision()
    state = telegram_platform
    state["tenant"] = envelope.tenant_id
    config = app.dependency_overrides[get_platform_settings]()
    with sync_session_maker() as session:
        bot = session.get(TelegramBotModel, envelope.bot_id)
        bot.credentials_encrypted = BotCredentials(config.BOT_CREDENTIALS_KEY).encrypt(
            envelope.bot_id,
            envelope.tenant_id,
            SecretStr("123456:fictional-verification-token"),
        )
        if replace_url:
            cipher = WebhookCredentials(config.BOT_CREDENTIALS_KEY)
            secret = SecretStr("fictional-existing-webhook-secret")
            session.add(
                TelegramBotWebhookModel(
                    bot_id=envelope.bot_id,
                    tenant_id=envelope.tenant_id,
                    url=f"https://old.example.com/webhooks/telegram/{envelope.bot_id}",
                    encrypted_secret=cipher.encrypt(
                        envelope.bot_id, envelope.tenant_id, secret
                    ),
                    secret_digest=cipher.digest(secret),
                    state="configured",
                )
            )
        session.commit()

    async def independent_session():
        async with async_session_maker() as session:
            yield session

    started, released = asyncio.Event(), asyncio.Event()
    calls = []

    async def provider(request):
        calls.append(request)
        started.set()
        await asyncio.wait_for(released.wait(), timeout=5)
        return httpx.Response(200, json={"ok": True, "result": True})

    app.dependency_overrides[get_session] = independent_session
    app.dependency_overrides[get_telegram] = lambda: TelegramClient(
        transport=httpx.MockTransport(provider)
    )
    route = base(state) + "/" + str(envelope.bot_id) + "/webhook"
    if replace_url:
        configured = config.model_copy(
            update={"TELEGRAM_WEBHOOK_ORIGIN": "https://new.example.com"}
        )
        app.dependency_overrides[get_platform_settings] = lambda: configured
    first = asyncio.create_task(
        client.post(
            route,
            headers=state["headers"],
            json={"dry_run": False, "replace_url": replace_url},
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        second = await client.post(
            route,
            headers=state["headers"],
            json={"dry_run": False, "replace_url": replace_url},
        )
        assert second.status_code == 409
    finally:
        released.set()
        response = await first
    assert response.status_code == 200 and len(calls) == 1
    assert (
        await client.post(route, headers=state["headers"], json={"dry_run": False})
    ).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("provider_status", [200, 400, 500])
async def test_replace_url_preserves_secret_dry_run_and_retry(
    client, db_session, telegram_platform, provider_status
):
    state = telegram_platform
    bot = (await create(client, state)).json()
    route = base(state) + "/" + bot["id"] + "/webhook"
    assert (
        await client.post(route, headers=state["headers"], json={"dry_run": False})
    ).status_code == 200
    original = dict(state["setup_calls"][0])
    config = app.dependency_overrides[get_platform_settings]()
    app.dependency_overrides[get_platform_settings] = lambda: config.model_copy(
        update={"TELEGRAM_WEBHOOK_ORIGIN": "https://new.example.com"}
    )
    # Origin changes alone preserve the old API contract and cause no provider call.
    unchanged = await client.post(
        route, headers=state["headers"], json={"dry_run": False}
    )
    assert unchanged.json()["webhook_url"] == original["url"]
    target = "https://new.example.com/webhooks/telegram/" + bot["id"]
    preview = await client.post(
        route, headers=state["headers"], json={"dry_run": True, "replace_url": True}
    )
    assert preview.status_code == 200 and preview.json()["webhook_url"] == target
    row = await db_session.get(
        TelegramBotWebhookModel, UUID(bot["id"]), populate_existing=True
    )
    assert row.url == original["url"] and row.state == "configured"
    encrypted, digest = row.encrypted_secret, row.secret_digest
    assert len(state["setup_calls"]) == 1
    state["setup_status"] = provider_status
    response = await client.post(
        route, headers=state["headers"], json={"dry_run": False, "replace_url": True}
    )
    assert response.status_code == (
        200 if provider_status == 200 else 503 if provider_status == 500 else 502
    )
    await db_session.refresh(row)
    assert row.url == target
    assert row.encrypted_secret == encrypted and row.secret_digest == digest
    assert (
        row.state == {200: "configured", 400: "failed", 500: "unknown"}[provider_status]
    )
    assert state["setup_calls"][1] == {**original, "url": target}
    assert original["secret_token"] not in response.text
    state["setup_status"] = 200
    # Ordinary retry resumes the persisted target after a failed/ambiguous replacement.
    retry = await client.post(route, headers=state["headers"], json={"dry_run": False})
    assert retry.status_code == 200 and retry.json()["webhook_url"] == target
    assert len(state["setup_calls"]) == (2 if provider_status == 200 else 3)
    repeated = await client.post(
        route, headers=state["headers"], json={"dry_run": False, "replace_url": True}
    )
    assert repeated.status_code == 200
    assert len(state["setup_calls"]) == (2 if provider_status == 200 else 3)


async def test_replacement_rejects_unauthorized_scope_and_invalid_input(
    client, telegram_platform
):
    state = telegram_platform
    bot = (await create(client, state)).json()
    route = base(state) + "/" + bot["id"] + "/webhook"
    payload = {"dry_run": False, "replace_url": True}
    assert (await client.post(route, json=payload)).status_code == 401
    state["role"] = "member"
    assert (
        await client.post(route, headers=state["headers"], json=payload)
    ).status_code == 403
    state["role"] = "owner"
    old_tenant = state["tenant"]
    state["tenant"] = uuid4()
    other_route = base(state) + "/" + bot["id"] + "/webhook"
    assert (
        await client.post(other_route, headers=state["headers"], json=payload)
    ).status_code == 404
    state["tenant"] = old_tenant
    for bad in ("true", 1, None):
        invalid = await client.post(
            route, headers=state["headers"], json={"dry_run": True, "replace_url": bad}
        )
        assert invalid.status_code == 422
    assert (
        await client.post(
            route,
            headers=state["headers"],
            json={**payload, "url": "https://arbitrary.example.com"},
        )
    ).status_code == 422
    assert state["setup_calls"] == []
