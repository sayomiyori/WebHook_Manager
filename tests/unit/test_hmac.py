from __future__ import annotations

import inspect

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


def test_verify_hmac_uses_compare_digest() -> None:
    source = inspect.getsource(verify_hmac_signature)
    assert "compare_digest" in source

