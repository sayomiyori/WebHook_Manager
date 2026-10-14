# Legacy admission without Redis

Legacy admission must accept a valid signed webhook while Redis is unavailable,
persist it, and allow the durable delivery scanner to recover after Redis returns.
HMAC/source validation, owner authorization, deduplication and platform gates stay
unchanged. Redis-backed platform bot registration stays fail closed.

The existing optional API-key prefix limits for legacy ingest/read use a shared
PostgreSQL sliding window instead of Redis. All API processes use database time
and a row lock; rejected requests also consume quota. Request failure, process
restart and Redis recovery cannot reset that quota. Store only a SHA-256 digest
of the existing scoped prefix and at most limit + 1 recent timestamps per key;
reclaim expired keys. Missing headers retain the existing skip behavior.

Add a forward migration after published revision 6e2f8a1c9b04. Do not edit or
publish unrelated local migrations. The private cached hardening release has an
additional 8f3b1c6d2a90 branch, so its isolated fixture upgrades both heads.
Published source has a single head. Apply no migration to the main deployment.

Acceptance: reproduce the Redis exception; real PostgreSQL concurrent quotas,
expiration, rejected-request accounting and process independence; offline HTTP
202/200 plus HMAC/owner/rate-limit denials; scanner recovery with one delivery per
event; migration up/down/up and model check on fresh databases; relevant suite,
Ruff, strict Mypy and fresh read-only security review. Preserve root data,
definitions, uploads, secrets and WSL hashes. No real Telegram/LLM calls.
