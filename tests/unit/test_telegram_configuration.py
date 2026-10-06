import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from src.core.config import Settings, settings


def configuration(**updates):
    values = settings.model_dump()
    values.update(
        PLATFORM_BOTS_ENABLED=True,
        PLATFORM_TELEGRAM_ENABLED=True,
        AUTHFORTRESS_BASE_URL="http://auth_service:8000",
        AUTHFORTRESS_WEBHOOK_SERVICE_KEY="fictional-issuer-key-at-least-32-bytes",
        WEBHOOK_AGENT_CONTEXT_KEY="fictional-context-key-at-least-32-bytes",
        BOT_CREDENTIALS_KEY=Fernet.generate_key().decode(),
        TELEGRAM_WEBHOOK_ORIGIN="https://demo.example.com",
        AGENTHUB_BASE_URL="http://agent_service:8000",
        WEBHOOK_AGENT_INGRESS_KEY="fictional-ingress-key-at-least-32-bytes",
    )
    values.update(updates)
    return Settings(_env_file=None, **values)


def test_telegram_configuration_validates_independent_api_and_worker():
    config = configuration()
    assert config.PLATFORM_PUBLICATION_MAX_ATTEMPTS == 10
    worker = configuration(
        PLATFORM_BOTS_ENABLED=False,
        PLATFORM_TELEGRAM_ENABLED=False,
        BOT_CREDENTIALS_KEY=None,
        TELEGRAM_WEBHOOK_ORIGIN=None,
    )
    worker.require_publication()
    assert not worker.PLATFORM_TELEGRAM_ENABLED


@pytest.mark.parametrize(
    "origin",
    [
        "http://demo.example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://user:pass@demo.example.com",
        "https://demo.example.com/a",
        "https://demo.example.com?x=1",
        "https://demo.example.com#x",
        "https://demo.example.com:1234",
    ],
)
def test_webhook_origin_rejects_unsafe_targets(origin):
    with pytest.raises(ValidationError):
        configuration(TELEGRAM_WEBHOOK_ORIGIN=origin)


@pytest.mark.parametrize("value", [0, 101])
def test_publication_attempts_are_bounded(value):
    with pytest.raises(ValidationError):
        configuration(PLATFORM_PUBLICATION_MAX_ATTEMPTS=value)


@pytest.mark.parametrize(
    "field",
    [
        "AGENTHUB_BASE_URL",
        "TELEGRAM_WEBHOOK_ORIGIN",
        "WEBHOOK_AGENT_INGRESS_KEY",
        "BOT_CREDENTIALS_KEY",
    ],
)
def test_telegram_optin_requires_configuration(field):
    with pytest.raises(ValidationError):
        configuration(**{field: None})


def test_ingress_key_cannot_reuse_context_key():
    with pytest.raises(ValidationError):
        configuration(
            WEBHOOK_AGENT_INGRESS_KEY="fictional-context-key-at-least-32-bytes"
        )
