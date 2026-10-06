from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
import pytest
import sentry_sdk
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError
from sentry_sdk.transport import Transport

from src.core.config import Settings
from src.core.logging import platform_sentry_breadcrumb, platform_sentry_event
from src.infrastructure.platform.clients import AuthFortressClient, TelegramClient
from src.infrastructure.platform.errors import PlatformError

TOKEN = "123456:fictional_TEST-token"
KEY = "fictional-service-key-with-32-bytes-minimum"
TENANT = uuid4()
USER = uuid4()


def issuer_body(**changes):
    return dict(
        user_id=str(USER),
        tenant_id=str(TENANT),
        role="owner",
        permission="bot.manage",
        allowed=True,
        **changes,
    )


async def test_authorize_canonical_context_and_request():
    def reply(request):
        assert request.method == "POST"
        assert (
            request.url == f"http://auth_service:8000/api/v1/tenants/{TENANT}/authorize"
        )
        assert request.headers["authorization"] == "Bearer fictional-access"
        assert request.content == b'{"permission":"bot.manage"}'
        assert request.extensions["timeout"] == dict(connect=2, read=5, write=5, pool=5)
        return httpx.Response(200, json=issuer_body())

    client = AuthFortressClient(
        "http://auth_service:8000", SecretStr(KEY), transport=httpx.MockTransport(reply)
    )
    context = await client.authorize(
        TENANT, SecretStr("fictional-access"), "bot.manage"
    )
    assert context.user_id == USER and context.tenant_id == TENANT


@pytest.mark.parametrize("status", [401, 403, 404, 302, 429, 500])
async def test_issuer_status_fails_closed_without_redirect(status):
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://untrusted.test"},
            json={"detail": TOKEN},
        )

    client = AuthFortressClient(
        "http://auth_service:8000", SecretStr(KEY), transport=httpx.MockTransport(reply)
    )
    with pytest.raises(PlatformError) as error:
        await client.authorize(TENANT, SecretStr("access"), "bot.manage")
    assert error.value.status_code == (status if status in {401, 403, 404} else 503)
    assert TOKEN not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", str(uuid4())),
        ("user_id", "invalid"),
        ("role", "admin"),
        ("permission", "bot.read"),
        ("allowed", 1),
        ("allowed", False),
    ],
)
async def test_issuer_rejects_invalid_context(field, value):
    body = issuer_body()
    body[field] = value
    client = AuthFortressClient(
        "http://auth_service:8000",
        SecretStr(KEY),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    with pytest.raises(PlatformError, match="Service unavailable"):
        await client.authorize(TENANT, SecretStr("access"), "bot.manage")


@pytest.mark.parametrize(
    "status,expected", [(200, 200), (404, 403), (401, 503), (403, 503), (500, 503)]
)
async def test_service_status_mapping(status, expected):
    def reply(request):
        assert request.headers["X-Service-Key"] == KEY
        assert "authorization" not in request.headers
        return httpx.Response(
            status, json={"tenant_id": str(TENANT), "is_active": True}
        )

    client = AuthFortressClient(
        "http://auth_service:8000", SecretStr(KEY), transport=httpx.MockTransport(reply)
    )
    if expected == 200:
        assert await client.tenant_active(TENANT) is True
    else:
        with pytest.raises(PlatformError) as error:
            await client.tenant_active(TENANT)
        assert error.value.status_code == expected


async def test_telegram_profile_uses_provider_id_and_optional_username(caplog):
    caplog.set_level(logging.DEBUG)

    def reply(request):
        assert request.url == f"https://api.telegram.org/bot{TOKEN}/getMe"
        return httpx.Response(
            200, json={"ok": True, "result": {"id": 999, "is_bot": True}}
        )

    profile = await TelegramClient(transport=httpx.MockTransport(reply)).get_me(
        SecretStr(TOKEN)
    )
    assert profile.id == 999 and profile.username is None
    assert TOKEN not in caplog.text


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, {"ok": False, "error_code": 401}, 400),
        (404, {"ok": False, "error_code": 404}, 400),
        (200, {"ok": False, "error_code": 401}, 400),
        (429, {"ok": False, "error_code": 429}, 503),
        (500, {"description": TOKEN}, 503),
        (302, {}, 503),
        (200, {"ok": 1, "result": {"id": 2, "is_bot": True}}, 503),
        (200, {"ok": True, "result": {"id": True, "is_bot": True}}, 503),
        (200, {"ok": True, "result": {"id": 0, "is_bot": True}}, 503),
        (200, {"ok": True, "result": {"id": 2**63, "is_bot": True}}, 503),
        (200, {"ok": True, "result": {"id": 2, "is_bot": 1}}, 503),
        (
            200,
            {"ok": True, "result": {"id": 2, "is_bot": True, "username": "a" * 129}},
            503,
        ),
    ],
)
async def test_telegram_errors_are_static(status, body, expected, caplog):
    caplog.set_level(logging.DEBUG)
    client = TelegramClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status, json=body, headers={"Location": "https://untrusted.test"}
            )
        )
    )
    with pytest.raises(PlatformError) as error:
        await client.get_me(SecretStr(TOKEN))
    assert error.value.status_code == expected
    assert TOKEN not in str(error.value) + caplog.text


@pytest.mark.parametrize(
    "content",
    [b"not-json", b"[]", b"x" * 65537],
    ids=["invalid-json", "array", "oversized"],
)
@pytest.mark.parametrize("provider", ["telegram", "issuer"])
async def test_invalid_or_oversized_responses(content, provider):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=content))
    with pytest.raises(PlatformError, match="Service unavailable"):
        if provider == "telegram":
            await TelegramClient(transport=transport).get_me(SecretStr(TOKEN))
        else:
            await AuthFortressClient(
                "http://auth_service:8000", SecretStr(KEY), transport=transport
            ).authorize(TENANT, SecretStr("access"), "bot.manage")


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
@pytest.mark.parametrize("provider", ["telegram", "issuer"])
async def test_transport_errors_do_not_leak_or_retry(error_type, provider, caplog):
    calls = []

    def reply(request):
        calls.append(request)
        raise error_type(TOKEN, request=request)

    transport = httpx.MockTransport(reply)
    with pytest.raises(PlatformError) as error:
        if provider == "telegram":
            await TelegramClient(transport=transport).get_me(SecretStr(TOKEN))
        else:
            await AuthFortressClient(
                "http://auth_service:8000", SecretStr(KEY), transport=transport
            ).authorize(TENANT, SecretStr("access"), "bot.manage")
    assert error.value.status_code == 503 and len(calls) == 1
    assert TOKEN not in str(error.value) + caplog.text
    assert error.value.__suppress_context__


def configuration(**overrides):
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test_test",
        REDIS_URL="redis://localhost/15",
        CELERY_BROKER_URL="redis://localhost/15",
        SECRET_KEY=overrides.pop(
            "SECRET_KEY", "fictional-test-secret-with-32-characters"
        ),
        **overrides,
    )


def test_platform_disabled_by_default():
    assert configuration().PLATFORM_BOTS_ENABLED is False


def test_complete_opt_in_configuration():
    configured = configuration(
        PLATFORM_BOTS_ENABLED=True,
        AUTHFORTRESS_BASE_URL="http://auth_service:8000",
        BOT_CREDENTIALS_KEY=Fernet.generate_key().decode(),
        AUTHFORTRESS_WEBHOOK_SERVICE_KEY=KEY,
        WEBHOOK_AGENT_CONTEXT_KEY="fictional-independent-agent-context-key",
    )
    assert configured.PLATFORM_BOTS_ENABLED
    assert KEY not in repr(configured)


def test_service_keys_cannot_be_reused():
    with pytest.raises(ValidationError, match="must be independent"):
        configuration(
            AUTHFORTRESS_WEBHOOK_SERVICE_KEY=KEY, WEBHOOK_AGENT_CONTEXT_KEY=KEY
        )


@pytest.mark.parametrize(
    "body",
    [
        {"tenant_id": str(uuid4()), "is_active": True},
        {"tenant_id": str(TENANT), "is_active": 1},
        {"tenant_id": str(TENANT)},
    ],
)
async def test_service_status_requires_canonical_active_tenant(body):
    client = AuthFortressClient(
        "http://auth_service:8000",
        SecretStr(KEY),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    with pytest.raises(PlatformError, match="Service unavailable"):
        await client.tenant_active(TENANT)


async def test_inactive_canonical_tenant_is_forbidden():
    client = AuthFortressClient(
        "http://auth_service:8000",
        SecretStr(KEY),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"tenant_id": str(TENANT), "is_active": False}
            )
        ),
    )
    with pytest.raises(PlatformError) as error:
        await client.tenant_active(TENANT)
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "token", ["", "invalid", "1:bad/route", "1:я", "1:" + "a" * 255]
)
async def test_invalid_token_never_reaches_provider(token):
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(200)

    client = TelegramClient(transport=httpx.MockTransport(reply))
    with pytest.raises(PlatformError) as error:
        await client.get_me(SecretStr(token))
    assert error.value.status_code == 400 and not calls


@pytest.mark.parametrize(
    "field",
    [
        "AUTHFORTRESS_WEBHOOK_SERVICE_KEY",
        "WEBHOOK_AGENT_CONTEXT_KEY",
        "BOT_CREDENTIALS_KEY",
    ],
)
def test_platform_key_cannot_reuse_delivery_secret(field):
    key = Fernet.generate_key().decode()
    with pytest.raises(ValidationError, match="must be independent"):
        configuration(SECRET_KEY=key, **{field: key})


class ChunkedReply(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False
        self.chunks = 0

    async def __aiter__(self):
        for _ in range(100):
            self.chunks += 1
            yield b"x" * 8192

    async def aclose(self):
        self.closed = True


async def test_stream_limit_stops_reading_and_closes_response():
    stream = ChunkedReply()
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    with pytest.raises(PlatformError):
        await TelegramClient(transport=transport).get_me(SecretStr(TOKEN))
    assert stream.closed and stream.chunks == 9


async def test_compressed_reply_fails_closed():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=ChunkedReply()
        )
    )
    with pytest.raises(PlatformError):
        await TelegramClient(transport=transport).get_me(SecretStr(TOKEN))


def test_sentry_drops_provider_events_transactions_and_http_breadcrumbs():
    event = {
        "spans": [{"description": f"GET https://api.telegram.org/bot{TOKEN}/getMe"}]
    }
    assert platform_sentry_event(event, {}) is None
    assert (
        platform_sentry_breadcrumb({"type": "http", "data": {"url": TOKEN}}, {}) is None
    )
    safe = platform_sentry_event(
        {
            "request": {
                "headers": {"authorization": TOKEN},
                "data": {"token": TOKEN},
                "cookies": TOKEN,
                "query_string": TOKEN,
                "url": "http://localhost/api/v1/tenants/bots",
            }
        },
        {},
    )
    assert TOKEN not in str(safe)
    assert safe["request"]["url"] == "http://localhost/api/v1/tenants/bots"


async def test_real_sentry_sdk_preserves_safe_events_without_credentials():
    envelopes = []

    class Capture(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    bearer = "fictional-issuer-access-secret"
    sdk_client = sentry_sdk.Client(
        dsn="https://public@example.invalid/1",
        transport=Capture,
        traces_sample_rate=1.0,
        before_send=platform_sentry_event,
        before_send_transaction=platform_sentry_event,
        before_breadcrumb=platform_sentry_breadcrumb,
        include_local_variables=False,
    )
    with sentry_sdk.isolation_scope() as scope:
        scope.set_client(sdk_client)
        with sentry_sdk.start_transaction(name="telegram-probe"):
            transport = httpx.MockTransport(
                lambda _: httpx.Response(200, json={"token": TOKEN})
            )
            try:
                await TelegramClient(transport=transport).get_me(SecretStr(TOKEN))
            except PlatformError as error:
                sentry_sdk.capture_exception(error)
        with sentry_sdk.start_transaction(name="issuer-probe"):
            transport = httpx.MockTransport(
                lambda _: httpx.Response(200, json={"invalid": KEY})
            )
            try:
                await AuthFortressClient(
                    "http://auth_service:8000", SecretStr(KEY), transport=transport
                ).authorize(TENANT, SecretStr(bearer), "bot.manage")
            except PlatformError as error:
                sentry_sdk.capture_exception(error)
        sdk_client.flush()
        sdk_client.close()

    assert any(envelope.get_event() for envelope in envelopes)
    transactions = [
        envelope.get_transaction_event()
        for envelope in envelopes
        if envelope.get_transaction_event()
    ]
    assert len(transactions) == 1
    assert transactions[0]["transaction"] == "issuer-probe"
    assert any(span.get("op") == "http.client" for span in transactions[0]["spans"])
    payload = json.dumps([envelope.serialize().decode() for envelope in envelopes])
    assert not any(secret in payload for secret in (TOKEN, KEY, bearer))


@pytest.mark.parametrize(
    "overrides",
    [
        {"PLATFORM_BOTS_ENABLED": True},
        {"AUTHFORTRESS_BASE_URL": "http://example.com"},
        {"AUTHFORTRESS_BASE_URL": "https://user:password@example.com"},
        {"AUTHFORTRESS_BASE_URL": "https://example.com?key=secret"},
        {"AUTHFORTRESS_BASE_URL": "https://example.com#fragment"},
        {"AUTHFORTRESS_WEBHOOK_SERVICE_KEY": "tiny"},
        {"WEBHOOK_AGENT_CONTEXT_KEY": "я" * 40},
        {"BOT_CREDENTIALS_KEY": TOKEN},
        {"RATE_LIMIT_BOT_REGISTER": 0},
    ],
)
def test_configuration_rejects_unsafe_values_without_input(overrides):
    with pytest.raises(ValidationError) as error:
        configuration(**overrides)
    assert TOKEN not in str(error.value) and "input_value" not in str(error.value)
