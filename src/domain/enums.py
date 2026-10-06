from __future__ import annotations

from enum import StrEnum


class DeliveryStatus(StrEnum):
    """Delivery lifecycle status."""

    PENDING = "pending"
    DELIVERING = "delivering"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"


class TelegramWebhookStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURING = "configuring"
    CONFIGURED = "configured"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TelegramIngressStatus(StrEnum):
    ACCEPTED = "accepted"
    IGNORED = "ignored"


class PlatformPublicationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"
