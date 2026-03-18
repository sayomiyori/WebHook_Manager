from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

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

