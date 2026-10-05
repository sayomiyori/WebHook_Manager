from __future__ import annotations

import json
import re
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from src.infrastructure.platform.errors import PlatformError


class BotCredentials:
    def __init__(self, key: SecretStr) -> None:
        self._fernet = Fernet(key.get_secret_value().encode("ascii"))

    def encrypt(self, bot_id: UUID, tenant_id: UUID, token: SecretStr) -> str:
        data = {
            "bot_id": str(bot_id),
            "tenant_id": str(tenant_id),
            "token": token.get_secret_value(),
        }
        return self._fernet.encrypt(json.dumps(data).encode()).decode()

    def decrypt(self, encrypted: str, bot_id: UUID, tenant_id: UUID) -> SecretStr:
        try:
            data = json.loads(self._fernet.decrypt(encrypted.encode()))
            if (
                not isinstance(data, dict)
                or data.get("bot_id") != str(bot_id)
                or data.get("tenant_id") != str(tenant_id)
                or not isinstance(data.get("token"), str)
                or len(data["token"]) > 256
                or re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", data["token"]) is None
            ):
                raise ValueError()
            return SecretStr(data["token"])
        except (InvalidToken, ValueError, UnicodeError, RecursionError):
            raise PlatformError() from None
