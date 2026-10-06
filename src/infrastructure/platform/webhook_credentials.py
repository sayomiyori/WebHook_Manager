from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from src.infrastructure.platform.errors import PlatformError


class WebhookCredentials:
    def __init__(self, key: SecretStr) -> None:
        self._fernet = Fernet(key.get_secret_value().encode("ascii"))

    def encrypt(self, bot_id: UUID, tenant_id: UUID, secret: SecretStr) -> str:
        data = {
            "purpose": "telegram_webhook",
            "bot_id": str(bot_id),
            "tenant_id": str(tenant_id),
            "secret": secret.get_secret_value(),
        }
        return self._fernet.encrypt(json.dumps(data).encode()).decode()

    def decrypt(self, ciphertext: str, bot_id: UUID, tenant_id: UUID) -> SecretStr:
        try:
            data = json.loads(self._fernet.decrypt(ciphertext.encode()))
            if (
                not isinstance(data, dict)
                or data.get("purpose") != "telegram_webhook"
                or data.get("bot_id") != str(bot_id)
                or data.get("tenant_id") != str(tenant_id)
                or not isinstance(data.get("secret"), str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", data["secret"]) is None
            ):
                raise ValueError()
            return SecretStr(data["secret"])
        except (InvalidToken, ValueError, UnicodeError, RecursionError):
            raise PlatformError() from None

    @staticmethod
    def digest(secret: SecretStr) -> str:
        return hashlib.sha256(secret.get_secret_value().encode("ascii")).hexdigest()
