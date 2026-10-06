from __future__ import annotations

import asyncio
import json
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict

from src.api.v1.schemas.telegram_ingress import TelegramIngressEnvelope
from src.core.config import Settings
from src.core.logging import suppress_platform_http_logging
from src.core.security import hmac_sha256_hex
from src.infrastructure.platform.clients import MAX_RESPONSE_BYTES, TIMEOUT


class AdmissionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    job_id: UUID
    state: Literal["pending", "processing", "completed", "failed", "unknown"]


class AdmissionError(Exception):
    def __init__(
        self, code: str, terminal: bool = False, retry_after: int | None = None
    ) -> None:
        super().__init__(code)
        self.code, self.terminal, self.retry_after = code, terminal, retry_after


class AgentAdmissionClient:
    def __init__(
        self, config: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        config.require_publication()
        self.config, self.transport = config, transport

    async def admit(self, envelope: TelegramIngressEnvelope) -> AdmissionReceipt:
        key = self.config.WEBHOOK_AGENT_INGRESS_KEY
        if key is None:
            raise AdmissionError("publication_configuration", terminal=True)
        body = json.dumps(
            envelope.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        signature = hmac_sha256_hex(secret=key.get_secret_value(), message=body)
        suppress_platform_http_logging()
        try:
            async with (
                asyncio.timeout(10),
                httpx.AsyncClient(
                    timeout=TIMEOUT,
                    verify=True,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client,
            ):
                async with client.stream(
                    "POST",
                    f"{self.config.AGENTHUB_BASE_URL}/internal/v1/telegram/updates",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept-Encoding": "identity",
                        "X-Webhook-Signature": f"sha256={signature}",
                    },
                ) as response:
                    if response.status_code in {400, 401, 403, 404, 409, 415, 422}:
                        raise AdmissionError("admission_rejected", terminal=True)
                    if (
                        response.headers.get("content-encoding", "identity")
                        != "identity"
                    ):
                        raise AdmissionError("invalid_admission_response")
                    data = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise AdmissionError("invalid_admission_response")
                        data.extend(chunk)
                    if response.status_code not in {200, 202}:
                        retry = None
                        if response.status_code == 429:
                            try:
                                decoded = json.loads(data)
                                value = (
                                    decoded.get("retry_after")
                                    if isinstance(decoded, dict)
                                    else None
                                )
                            except (ValueError, UnicodeError, RecursionError):
                                value = None
                            header = response.headers.get("Retry-After", "")
                            if (
                                header.isascii()
                                and header.isdigit()
                                and len(header) <= 4
                            ):
                                value = int(header)
                            if type(value) is int and 1 <= value <= 3600:
                                retry = value
                        raise AdmissionError("admission_unavailable", retry_after=retry)
                    receipt = AdmissionReceipt.model_validate_json(data)
                    if receipt.event_id != envelope.event_id:
                        raise AdmissionError("invalid_admission_response")
                    return receipt
        except (httpx.HTTPError, TimeoutError):
            raise AdmissionError("admission_unavailable") from None
        except (ValueError, UnicodeError, RecursionError):
            raise AdmissionError("invalid_admission_response") from None
