from __future__ import annotations

import hashlib
import hmac
import secrets


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def hmac_sha256_hex(*, secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_hmac_signature(payload: bytes, secret: str, signature_header: str) -> bool:
    # X-Webhook-Signature: sha256=<hex>
    if not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    provided = signature_header.removeprefix(prefix).strip()
    expected = hmac_sha256_hex(secret=secret, message=payload)
    return hmac.compare_digest(provided, expected)


def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext_key, prefix, sha256_hash)."""
    plaintext = "wh_" + secrets.token_urlsafe(32)
    prefix = plaintext[:8]
    key_hash = hash_api_key(plaintext)
    return plaintext, prefix, key_hash

