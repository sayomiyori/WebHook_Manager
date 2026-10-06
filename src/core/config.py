from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import PostgresDsn, RedisDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", hide_input_in_errors=True)

    APP_NAME: str = "webhook-manager"
    DEBUG: bool = False

    DATABASE_URL: PostgresDsn
    REDIS_URL: RedisDsn

    SECRET_KEY: str

    CELERY_BROKER_URL: RedisDsn
    SENTRY_DSN: str | None = None

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    CORS_ORIGINS: list[str] = []
    TRUSTED_HOSTS: list[str] = ["*"]

    RATE_LIMIT_INGEST: int = 100
    RATE_LIMIT_READ: int = 1000
    MAX_DELIVERY_ATTEMPTS: int = 5
    DELIVERY_TIMEOUT_SECONDS: int = 10

    PLATFORM_BOTS_ENABLED: bool = False
    AUTHFORTRESS_BASE_URL: str | None = None
    BOT_CREDENTIALS_KEY: SecretStr | None = None
    AUTHFORTRESS_WEBHOOK_SERVICE_KEY: SecretStr | None = None
    WEBHOOK_AGENT_CONTEXT_KEY: SecretStr | None = None
    RATE_LIMIT_BOT_REGISTER: int = 10
    PLATFORM_TELEGRAM_ENABLED: bool = False
    TELEGRAM_WEBHOOK_ORIGIN: str | None = None
    AGENTHUB_BASE_URL: str | None = None
    WEBHOOK_AGENT_INGRESS_KEY: SecretStr | None = None
    PLATFORM_PUBLICATION_MAX_ATTEMPTS: int = 10

    @field_validator("AGENTHUB_BASE_URL")
    @classmethod
    def _validate_agent_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        checked = value
        if (
            value.startswith("http://agent_service")
            and urlsplit(value).hostname == "agent_service"
        ):
            checked = "http://auth_service" + value[len("http://agent_service") :]
        cls._validate_issuer_url(checked)
        return value.rstrip("/")

    @field_validator("TELEGRAM_WEBHOOK_ORIGIN")
    @classmethod
    def _validate_webhook_origin(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = urlsplit(value)
            host = parsed.hostname or ""
            valid = (
                parsed.scheme == "https"
                and parsed.port in {None, 443, 80, 88, 8443}
                and parsed.username is None
                and parsed.password is None
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
                and "?" not in value
                and "#" not in value
                and all(33 <= ord(c) <= 126 for c in value)
                and re.fullmatch(
                    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}", host
                )
                is not None
                and not host.endswith((".localhost", ".local", ".internal"))
            )
            try:
                ipaddress.ip_address(host)
                valid = False
            except ValueError:
                pass
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Invalid public Telegram webhook origin")
        return value.rstrip("/")

    @field_validator("PLATFORM_PUBLICATION_MAX_ATTEMPTS")
    @classmethod
    def _validate_publication_attempts(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("Publication attempts must be between 1 and 100")
        return value

    def require_publication(self) -> None:
        if not all(
            (
                self.AUTHFORTRESS_BASE_URL,
                self.AUTHFORTRESS_WEBHOOK_SERVICE_KEY,
                self.AGENTHUB_BASE_URL,
                self.WEBHOOK_AGENT_INGRESS_KEY,
            )
        ):
            raise ValueError("Platform publication configuration is incomplete")

    @field_validator("AUTHFORTRESS_BASE_URL")
    @classmethod
    def _validate_issuer_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = urlsplit(value)
            port = parsed.port
            valid = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and "?" not in value
                and "#" not in value
                and parsed.path in {"", "/"}
                and all(ord(char) > 32 and ord(char) < 127 for char in value)
                and (port is None or port > 0)
                and (
                    parsed.scheme == "https"
                    or parsed.hostname
                    in {"auth_service", "localhost", "127.0.0.1", "::1"}
                )
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Invalid AuthFortress base URL")
        return value.rstrip("/")

    @field_validator(
        "AUTHFORTRESS_WEBHOOK_SERVICE_KEY",
        "WEBHOOK_AGENT_CONTEXT_KEY",
        "WEBHOOK_AGENT_INGRESS_KEY",
    )
    @classmethod
    def _validate_service_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None
        raw = value.get_secret_value()
        if not 32 <= len(raw) <= 256 or not all(33 <= ord(c) <= 126 for c in raw):
            raise ValueError("Invalid platform service key")
        return value

    @field_validator("BOT_CREDENTIALS_KEY")
    @classmethod
    def _validate_credentials_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None
        try:
            Fernet(value.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeError):
            raise ValueError("Invalid bot credentials key") from None
        return value

    @field_validator("RATE_LIMIT_BOT_REGISTER")
    @classmethod
    def _validate_registration_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Bot registration limit must be positive")
        return value

    @model_validator(mode="after")
    def _validate_platform_configuration(self) -> Settings:
        keys = [
            key.get_secret_value()
            for key in (
                self.AUTHFORTRESS_WEBHOOK_SERVICE_KEY,
                self.WEBHOOK_AGENT_CONTEXT_KEY,
                self.BOT_CREDENTIALS_KEY,
                self.WEBHOOK_AGENT_INGRESS_KEY,
            )
            if key is not None
        ]
        if self.SECRET_KEY in keys or len(keys) != len(set(keys)):
            raise ValueError("Platform keys must be independent")
        if self.PLATFORM_BOTS_ENABLED and not all(
            (
                self.AUTHFORTRESS_BASE_URL,
                self.BOT_CREDENTIALS_KEY,
                self.AUTHFORTRESS_WEBHOOK_SERVICE_KEY,
                self.WEBHOOK_AGENT_CONTEXT_KEY,
            )
        ):
            raise ValueError("Platform bot configuration is incomplete")
        if self.PLATFORM_TELEGRAM_ENABLED:
            if not self.PLATFORM_BOTS_ENABLED or not self.TELEGRAM_WEBHOOK_ORIGIN:
                raise ValueError("Platform Telegram configuration is incomplete")
            self.require_publication()
        return self

    @field_validator("SECRET_KEY")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        if len(value) < 32:
            msg = "SECRET_KEY must be at least 32 characters long"
            raise ValueError(msg)
        return value

    @property
    def database_url(self) -> PostgresDsn:
        return self.DATABASE_URL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
