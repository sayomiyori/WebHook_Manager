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

