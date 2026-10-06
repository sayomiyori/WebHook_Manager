from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from src.infrastructure.platform.errors import PlatformError
from src.infrastructure.platform.webhook_credentials import WebhookCredentials


def test_webhook_secret_is_encrypted_and_bound():
    cipher = WebhookCredentials(SecretStr(Fernet.generate_key().decode()))
    bot, tenant = uuid4(), uuid4()
    secret = SecretStr("fictional-webhook-secret-with-32-bytes")
    encrypted = cipher.encrypt(bot, tenant, secret)
    assert secret.get_secret_value() not in encrypted
    assert cipher.decrypt(encrypted, bot, tenant) == secret
    assert len(cipher.digest(secret)) == 64
    for other_bot, other_tenant in [(uuid4(), tenant), (bot, uuid4())]:
        with pytest.raises(PlatformError, match="Service unavailable"):
            cipher.decrypt(encrypted, other_bot, other_tenant)
    with pytest.raises(PlatformError):
        WebhookCredentials(SecretStr(Fernet.generate_key().decode())).decrypt(
            encrypted, bot, tenant
        )
