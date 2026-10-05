from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import select

from src.api.main import app
from src.api.v1.dependencies.platform import (
    get_issuer,
    get_platform_settings,
    get_registration_limiter,
    get_telegram,
)
from src.core.config import settings
from src.core.dependencies import get_session
from src.infrastructure.cache.bot_registration_limiter import BotRegistrationLimiter
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.models.telegram_bot import TelegramBotModel
from src.infrastructure.db.repositories.telegram_bot_repository import (
    TelegramBotRepository,
)
from src.infrastructure.platform.clients import AuthFortressClient, TelegramClient
from src.infrastructure.platform.credentials import BotCredentials

TOKEN = "123456:fictional_REGISTRY-token"


@pytest.fixture
def platform(client):
    state = {
        "tenant": uuid4(),
        "user": uuid4(),
        "telegram_id": uuid4().int % (2**50),
        "role": "owner",
        "issuer_status": 200,
        "tenant_status": 200,
        "calls": [],
        "authorize_calls": 0,
        "revoke_after_provider": False,
        "deactivate_during_status": None,
    }
    key = Fernet.generate_key().decode()
    configured = settings.model_copy(
        update={
            "PLATFORM_BOTS_ENABLED": True,
            "BOT_CREDENTIALS_KEY": SecretStr(key),
            "AUTHFORTRESS_BASE_URL": "http://auth_service:8000",
            "AUTHFORTRESS_WEBHOOK_SERVICE_KEY": SecretStr(
                "fictional-issuer-service-key-32-bytes"
            ),
            "WEBHOOK_AGENT_CONTEXT_KEY": SecretStr(
                "fictional-agent-context-service-key-32-bytes"
            ),
        }
    )

    async def issuer(request):
        state["calls"].append(request.url.path)
        if request.url.path.startswith("/internal/"):
            if state["deactivate_during_status"]:
                async with async_session_maker() as session:
                    await TelegramBotRepository(session).deactivate(
                        state["deactivate_during_status"], state["tenant"]
                    )
                    await session.commit()
            return httpx.Response(
                state["tenant_status"],
                json={"tenant_id": str(state["tenant"]), "is_active": True},
            )
        permission = json.loads(request.content)["permission"]
        status = state["issuer_status"]
        state["authorize_calls"] += 1
        if state["revoke_after_provider"] and state["authorize_calls"] > 1:
            status = 401
        if state["role"] == "member" and permission == "bot.manage":
            status = 403
        return httpx.Response(
            status,
            json={
                "user_id": str(state["user"]),
                "tenant_id": str(state["tenant"]),
                "role": state["role"],
                "permission": permission,
                "allowed": True,
            },
        )

    def telegram(request):
        state["calls"].append("telegram")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "id": state["telegram_id"],
                    "is_bot": True,
                    "username": "fictional_bot",
                },
            },
        )

    app.dependency_overrides[get_platform_settings] = lambda: configured
    app.dependency_overrides[get_issuer] = lambda: AuthFortressClient(
        configured.AUTHFORTRESS_BASE_URL,
        configured.AUTHFORTRESS_WEBHOOK_SERVICE_KEY,
        transport=httpx.MockTransport(issuer),
    )
    app.dependency_overrides[get_telegram] = lambda: TelegramClient(
        transport=httpx.MockTransport(telegram)
    )
    state["key"] = key
    state["headers"] = {"Authorization": "Bearer fictional-access"}
    state["context_headers"] = {
        "X-Service-Key": configured.WEBHOOK_AGENT_CONTEXT_KEY.get_secret_value()
    }
    return state


async def test_reauthorize_denial_rolls_back_before_insert(
    client, db_session, platform
):
    platform["revoke_after_provider"] = True
    assert (await create(client, platform)).status_code == 401
    assert platform["calls"].count("telegram") == 1
    assert (
        await db_session.execute(
            select(TelegramBotModel).where(
                TelegramBotModel.tenant_id == platform["tenant"]
            )
        )
    ).scalars().all() == []


async def test_concurrent_duplicate_registrations_have_one_winner(client, platform):
    async def separate_session():
        async with async_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = separate_session
    responses = await asyncio.gather(create(client, platform), create(client, platform))
    assert sorted(response.status_code for response in responses) == [201, 409]
    rows = (await client.get(base(platform), headers=platform["headers"])).json()[
        "items"
    ]
    assert len(rows) == 1
    platform["tenant"] = uuid4()
    assert (await create(client, platform)).status_code == 409


async def test_context_rereads_bot_after_issuer_call(client, platform):
    async def separate_session():
        async with async_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = separate_session
    bot = (await create(client, platform)).json()
    platform["deactivate_during_status"] = UUID(bot["id"])
    response = await client.get(
        "/internal/v1/bots/" + bot["id"] + "/context",
        headers=platform["context_headers"],
    )
    assert response.status_code == 403


async def test_redis_outage_prevents_provider(client, platform):
    redis = Redis.from_url("redis://127.0.0.1:1/15", socket_connect_timeout=0.1)
    app.dependency_overrides[get_registration_limiter] = lambda: BotRegistrationLimiter(
        redis, 10
    )
    try:
        assert (await create(client, platform)).status_code == 503
        assert "telegram" not in platform["calls"]
    finally:
        await redis.aclose()


async def test_cursor_bounds_and_inactive_listing(client, platform):
    bots = []
    for _ in range(3):
        platform["telegram_id"] += 1
        bots.append((await create(client, platform)).json())
    expected = sorted(bots, key=lambda bot: bot["id"])
    first = (
        await client.get(
            base(platform), params={"limit": 2}, headers=platform["headers"]
        )
    ).json()
    assert first["items"] == expected[:2]
    rest = (
        await client.get(
            base(platform),
            params={"limit": 2, "cursor": first["next_cursor"]},
            headers=platform["headers"],
        )
    ).json()
    assert rest["items"] == expected[2:] and rest["next_cursor"] is None
    response = await client.get(
        base(platform),
        params={"cursor": str(UUID(int=2**128 - 1))},
        headers=platform["headers"],
    )
    assert response.json()["items"] == []
    response = await client.get(
        base(platform), params={"limit": 101}, headers=platform["headers"]
    )
    assert response.status_code == 422 and response.json() == {
        "detail": "Invalid bot request"
    }


async def test_oversized_stream_and_malformed_json_are_sanitized(client, platform):
    async def oversized():
        yield b'{"token":"'
        yield TOKEN.encode() * 200

    response = await client.post(
        base(platform),
        content=oversized(),
        headers={**platform["headers"], "Content-Type": "application/json"},
    )
    assert response.status_code == 422 and TOKEN not in response.text
    response = await client.post(
        base(platform),
        content=b"bad-json",
        headers={**platform["headers"], "Content-Type": "application/json"},
    )
    assert response.status_code == 422


async def test_missing_bearer_and_service_keys(client, platform):
    assert (
        await client.post(base(platform), json={"name": "x", "token": TOKEN})
    ).status_code == 401
    for headers in [{}, {"X-Service-Key": "wrong"}, {"X-Service-Key": "x" * 257}]:
        response = await client.get(
            f"/internal/v1/bots/{uuid4()}/context", headers=headers
        )
        assert response.status_code == 401 and response.json() == {
            "detail": "Invalid service key"
        }


def test_credentials_reject_swapped_payload_and_wrong_key():
    cipher = BotCredentials(SecretStr(Fernet.generate_key().decode()))
    bot, tenant = uuid4(), uuid4()
    encrypted = cipher.encrypt(bot, tenant, SecretStr(TOKEN))
    assert cipher.decrypt(encrypted, bot, tenant).get_secret_value() == TOKEN
    from src.infrastructure.platform.errors import PlatformError

    for requested_bot, requested_tenant in [(uuid4(), tenant), (bot, uuid4())]:
        with pytest.raises(PlatformError):
            cipher.decrypt(encrypted, requested_bot, requested_tenant)
    with pytest.raises(PlatformError):
        BotCredentials(SecretStr(Fernet.generate_key().decode())).decrypt(
            encrypted, bot, tenant
        )


def base(platform):
    return f"/api/v1/tenants/{platform['tenant']}/bots"


async def create(client, platform):
    return await client.post(
        base(platform),
        headers=platform["headers"],
        json={"name": " Support ", "token": TOKEN},
    )


async def test_bot_registry_encrypted_read_list_deactivate(
    client, db_session, platform
):
    result = await create(client, platform)
    assert result.status_code == 201
    bot = result.json()
    assert bot["name"] == "Support" and bot["webhook_status"] == "not_configured"
    assert TOKEN not in result.text and "credentials_encrypted" not in result.text
    row = await db_session.get(TelegramBotModel, UUID(bot["id"]))
    decrypted = json.loads(
        Fernet(platform["key"].encode()).decrypt(row.credentials_encrypted.encode())
    )
    assert decrypted == {
        "bot_id": bot["id"],
        "tenant_id": str(platform["tenant"]),
        "token": TOKEN,
    }
    assert TOKEN not in row.credentials_encrypted
    listing = await client.get(base(platform), headers=platform["headers"])
    assert listing.json()["items"] == [bot]
    read = await client.get(
        base(platform) + "/" + bot["id"], headers=platform["headers"]
    )
    assert read.json() == bot
    deactivated = await client.post(
        base(platform) + "/" + bot["id"] + "/deactivate", headers=platform["headers"]
    )
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    again = await client.post(
        base(platform) + "/" + bot["id"] + "/deactivate", headers=platform["headers"]
    )
    assert again.json() == deactivated.json()
    duplicate = await create(client, platform)
    assert duplicate.status_code == 409


async def test_cross_tenant_hidden_even_for_known_bot(client, platform):
    bot = (await create(client, platform)).json()
    platform["tenant"] = uuid4()
    for suffix, method in [("", "get"), ("/deactivate", "post")]:
        response = await getattr(client, method)(
            base(platform) + "/" + bot["id"] + suffix, headers=platform["headers"]
        )
        assert response.status_code == 404 and response.json() == {"error": "not_found"}
    assert (await client.get(base(platform), headers=platform["headers"])).json()[
        "items"
    ] == []


@pytest.mark.parametrize("status", [401, 403, 404, 503])
async def test_issuer_denial_creates_no_bot(client, db_session, platform, status):
    platform["issuer_status"] = status
    response = await create(client, platform)
    assert response.status_code == status
    assert "telegram" not in platform["calls"]
    assert (
        await db_session.execute(
            select(TelegramBotModel).where(
                TelegramBotModel.tenant_id == platform["tenant"]
            )
        )
    ).scalars().all() == []


async def test_member_can_read_but_not_create_or_deactivate(client, platform):
    bot = (await create(client, platform)).json()
    platform["role"] = "member"
    assert (
        await client.get(base(platform), headers=platform["headers"])
    ).status_code == 200
    assert (await create(client, platform)).status_code == 403
    assert (
        await client.post(
            base(platform) + "/" + bot["id"] + "/deactivate",
            headers=platform["headers"],
        )
    ).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "token": "123:bad/route"},
        {"name": " ", "token": TOKEN},
        {"name": "x", "token": TOKEN, "tenant_id": "forged"},
        {"name": 3, "token": TOKEN},
        {"name": "x", "token": 3},
    ],
)
async def test_invalid_bot_body_is_sanitized(client, platform, body):
    response = await client.post(base(platform), headers=platform["headers"], json=body)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid bot request"}
    assert TOKEN not in response.text and "telegram" not in platform["calls"]


async def test_service_context_has_no_credentials_and_checks_status(client, platform):
    bot = (await create(client, platform)).json()
    url = "/internal/v1/bots/" + bot["id"] + "/context"
    assert (await client.get(url, headers=platform["headers"])).status_code == 401
    context = await client.get(url, headers=platform["context_headers"])
    assert context.status_code == 200
    assert context.json() == {
        "bot_id": bot["id"],
        "tenant_id": str(platform["tenant"]),
        "telegram_bot_id": platform["telegram_id"],
        "is_active": True,
    }
    platform["tenant_status"] = 404
    assert (
        await client.get(url, headers=platform["context_headers"])
    ).status_code == 403


async def test_registration_quota_blocks_provider(client, platform):
    for _ in range(10):
        response = await create(client, platform)
        assert response.status_code in {201, 409}
    calls = platform["calls"].count("telegram")
    assert (await create(client, platform)).status_code == 429
    assert platform["calls"].count("telegram") == calls


async def test_platform_disabled_fails_closed(client):
    response = await client.get(f"/api/v1/tenants/{uuid4()}/bots")
    assert response.status_code == 503
