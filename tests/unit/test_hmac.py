from __future__ import annotations

import inspect

import pytest

from src.core.security import hmac_sha256_hex, verify_hmac_signature


def test_valid_hmac_signature_returns_true() -> None:
    payload = b'{"a":1}'
    secret = "super-secret"
    signature = hmac_sha256_hex(secret=secret, message=payload)
    assert verify_hmac_signature(payload, secret, f"sha256={signature}") is True


def test_wrong_secret_returns_false() -> None:
    payload = b'{"a":1}'
    signature = hmac_sha256_hex(secret="secret-a", message=payload)
    assert verify_hmac_signature(payload, "secret-b", f"sha256={signature}") is False


@pytest.mark.parametrize(
    "provided", ["\u044f", "x" * 64, "0" * 63, "0" * 65, "\u00e9" * 64]
)
def test_malformed_hmac_signature_is_rejected(provided: str) -> None:
    result = verify_hmac_signature(b"{}", "test-only-secret", f"sha256={provided}")
    assert result is False


def test_verify_hmac_uses_compare_digest() -> None:
    source = inspect.getsource(verify_hmac_signature)
    assert "compare_digest" in source


def test_webhook_headers_strip_credentials_and_transport_headers() -> None:
    from src.core.security import sanitize_webhook_headers

    assert sanitize_webhook_headers(
        {
            "Authorization": "test-only",
            "X-API-Key": "test-only",
            "Cookie": "test-only",
            "Connection": "X-Hop",
            "x-hop": "private",
            "Host": "internal",
            "Content-Length": "999",
            "X-Webhook-Signature": "old",
            "X-Event-Type": "test",
        }
    ) == {"X-Event-Type": "test"}


def test_celery_worker_imports_delivery_module() -> None:
    from src.infrastructure.queue.celery_app import celery_app

    assert "src.infrastructure.queue.tasks.deliver_webhook" in celery_app.conf.include
