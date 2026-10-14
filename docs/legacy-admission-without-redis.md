# Legacy admission during a Redis outage

Legacy ingest/read quotas now use PostgreSQL instead of Redis. A valid signed
legacy webhook can be saved while Redis is unavailable; the existing permanent
delivery scanner publishes pending intents when the broker returns.

HMAC/source validation, owner authorization, optional API-key header behavior,
ingest/read prefixes and configured sliding-window limits are unchanged.
Platform bot registration retains its Redis limiter and fails closed on outage.
PostgreSQL is required: a failed quota transaction cannot authorize admission.
Readiness still reports Redis unavailable while the broker is stopped.

All API processes lock the same hashed-prefix row and use database time.
Rejected requests also consume quota, independently of the request transaction.
Redis recovery and API process replacement cannot reset quota. Each key retains
at most `limit + 1` recent timestamps; indexed expiration reclaims up to 100 old
keys per request in a separate transaction. No new dependencies or settings.

Apply the new forward migration `c42d8e91a730` before starting the updated API.
Published source has one head after `6e2f8a1c9b04`; migration initializes empty
quota state rather than importing volatile Redis windows. No main deployment
migration or runtime replacement was performed during this verification.

## Verification on 2026-10-14

The final publishable source passed 351 tests (85.86% coverage) and nine focused
quota/dependency tests. Migration up/down/up and model check passed. Ruff,
strict Mypy and 28 root regressions passed; fresh read-only adversarial/security
review approved the change. EXPLAIN confirmed the expiration index is usable
with `statement_timestamp()`; quota time is sampled after the atomic row lock.

Commands ran with explicit `TEST_DATABASE_URL`/`TEST_REDIS_URL` pointing to new,
owned PostgreSQL/Redis fixtures; the database name ends in `_test`. No `.env`,
main volumes or real Telegram/LLM credentials were used.

```powershell
.venv/Scripts/python.exe -m alembic upgrade heads
.venv/Scripts/python.exe -m alembic downgrade 6e2f8a1c9b04
.venv/Scripts/python.exe -m alembic upgrade heads
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m pytest tests/integration/test_rate_limiter.py tests/unit/test_rate_limit_dependencies.py -q
.venv/Scripts/python.exe -m pytest tests/ --cov=src --cov-report=term --cov-fail-under=80
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/ alembic/
.venv/Scripts/python.exe -m mypy src/ --strict
```

The local cached hardening release also contains the unrelated `8f3b1c6d2a90`
branch. Its private fixture upgrades both heads; the publishable source was
separately checked from `git archive HEAD` plus only this task's files, with the
single new head. Existing applied migrations and unrelated changes are preserved.

The NexusCore `scripts/verify_stack.py --scanners` fixture stops its own Redis
before HTTP admission. It requires 202 for admission, 200 for sequential and
concurrent duplicates, 401 for invalid HMAC/API-key access and 429 for exhausted
quota. A second Python process sees the same quota; Redis restoration keeps the
429. The real scanner survives database/broker outages, recovers two signed
numeric-IP callbacks, and restarts without duplicate delivery. Receipts retain
only safe metadata. Test containers are stopped; their new volumes are preserved.

Root database rows/schema/sequences/metadata, nine existing container definitions,
upload content/modes, `.env`, release artifacts and WSL configuration hashes were
compared before and after. Real providers, external activation and load tests
were outside this local check.
