from __future__ import annotations

import asyncio
import json
import re
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, SecretStr, StrictBool, StrictInt, StrictStr

from src.core.config import Settings
from src.core.logging import suppress_platform_http_logging
from src.infrastructure.platform.errors import PlatformError

TIMEOUT = httpx.Timeout(5.0, connect=2.0)
MAX_RESPONSE_BYTES = 65536


class AuthorizedContext(BaseModel):
    user_id: UUID
    tenant_id: UUID
    role: Literal["owner", "member"]
    permission: Literal["bot.read", "bot.manage"]
    allowed: StrictBool


class TenantStatus(BaseModel):
    tenant_id: UUID
    is_active: StrictBool


class TelegramProfile(BaseModel):
    id: Annotated[StrictInt, Field(gt=0, le=2**63 - 1)]
    is_bot: StrictBool
    username: Annotated[StrictStr, Field(max_length=128)] | None = None


async def _request(
    method: str,
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None,
    headers: dict[str, str] | None = None,
    body: dict[str, str] | None = None,
) -> tuple[int, Any]:
    # Both clients require bounded replies and credential-safe HTTP telemetry.
    suppress_platform_http_logging()
    try:
        async with (
            asyncio.timeout(10),
            httpx.AsyncClient(
                timeout=TIMEOUT,
                follow_redirects=False,
                trust_env=False,
                verify=True,
                transport=transport,
            ) as client,
            client.stream(
                method,
                url,
                headers={"Accept-Encoding": "identity", **(headers or {})},
                json=body,
            ) as response,
        ):
            if response.headers.get("content-encoding", "identity") != "identity":
                raise PlatformError()
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=8192):
                if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise PlatformError()
                data.extend(chunk)
            try:
                decoded = json.loads(data)
            except (ValueError, UnicodeError, RecursionError):
                decoded = None
            return response.status_code, decoded
    except (httpx.HTTPError, TimeoutError, ValueError):
        raise PlatformError() from None


class AuthFortressClient:
    def __init__(
        self,
        base_url: str,
        service_key: SecretStr | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        try:
            validated = Settings._validate_issuer_url(base_url)
        except ValueError:
            raise PlatformError() from None
        if not validated:
            raise PlatformError()
        self._base_url = validated
        self._service_key = service_key
        self._transport = transport

    async def authorize(
        self,
        tenant_id: UUID,
        bearer: SecretStr,
        permission: Literal["bot.read", "bot.manage"],
    ) -> AuthorizedContext:
        raw = bearer.get_secret_value()
        if not raw or not raw.isascii() or any(ord(c) <= 32 for c in raw):
            raise PlatformError(401)
        status, body = await _request(
            "POST",
            f"{self._base_url}/api/v1/tenants/{tenant_id}/authorize",
            transport=self._transport,
            headers={"Authorization": f"Bearer {raw}"},
            body={"permission": permission},
        )
        if status in {401, 403, 404}:
            raise PlatformError(status)
        if status != 200:
            raise PlatformError()
        try:
            context = AuthorizedContext.model_validate(body)
        except ValueError:
            raise PlatformError() from None
        if (
            context.tenant_id != tenant_id
            or context.permission != permission
            or context.allowed is not True
        ):
            raise PlatformError()
        return context

    async def tenant_active(self, tenant_id: UUID) -> bool:
        try:
            key = Settings._validate_service_key(self._service_key)
        except ValueError:
            raise PlatformError() from None
        if key is None:
            raise PlatformError()
        status, body = await _request(
            "GET",
            f"{self._base_url}/internal/v1/tenants/{tenant_id}/status",
            transport=self._transport,
            headers={"X-Service-Key": key.get_secret_value()},
        )
        if status == 404:
            raise PlatformError(403)
        if status != 200:
            raise PlatformError()
        try:
            context = TenantStatus.model_validate(body)
        except ValueError:
            raise PlatformError() from None
        if context.tenant_id != tenant_id or context.is_active is not True:
            raise PlatformError()
        return True


class TelegramClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def get_me(self, token: SecretStr) -> TelegramProfile:
        raw = token.get_secret_value()
        if len(raw) > 256 or re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", raw) is None:
            raise PlatformError(400)
        status, body = await _request(
            "GET",
            f"https://api.telegram.org/bot{raw}/getMe",
            transport=self._transport,
        )
        if (
            status in {200, 401, 404}
            and isinstance(body, dict)
            and body.get("ok") is False
            and type(body.get("error_code")) is int
            and body["error_code"] in {401, 404}
        ):
            raise PlatformError(400)
        if status != 200 or not isinstance(body, dict) or body.get("ok") is not True:
            raise PlatformError()
        try:
            profile = TelegramProfile.model_validate(body.get("result"))
        except ValueError:
            raise PlatformError() from None
        if profile.is_bot is not True:
            raise PlatformError()
        return profile
