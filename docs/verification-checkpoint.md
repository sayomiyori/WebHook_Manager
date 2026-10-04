# Verification checkpoint — 2026-10-03

Status: **Verified locally with unresolved acceptance/security findings**. This is not a production-ready claim.

## Scope and isolation

The existing service was tested independently on Windows with CPython 3.12.10,
PostgreSQL 16 and Redis 7. No NexusCore/demo database was cleaned or changed.
Existing user changes in `docker-compose.yml` and `.cursor/` were preserved.
No commits, branches, pushes, dependency additions, DROP, TRUNCATE or downgrade
commands were executed. Tests use rollback/savepoints on real PostgreSQL.

## Changes

- Management endpoints require an active API key. Supplied owner IDs must match
  the authenticated owner. Event/source, subscription/endpoint/source and
  delivery/event/endpoint ownership is checked; another owner receives 403.
- Original query/body shapes are retained. Previously unauthenticated management
  callers must now supply `X-API-Key`; this security contract change is intentional.
- Ingress and delivery strip credential and hop-by-hop headers. Previously stored
  events are sanitized at delivery too. Receiver HMAC is regenerated for its body.
- Ambiguous owner-scoped source slugs fail closed on the public ingest route.
- Celery explicitly imports the delivery task module at worker startup. Before
  the fix, a real worker discarded `deliver_webhook` as an unregistered task.
- Tests require explicit `TEST_DATABASE_URL` ending `_test` and `TEST_REDIS_URL`.
  They no longer load ordinary `.env` values or truncate tables. CI applies
  migrations before tests; eager cross-connection tests became queue-boundary
  tests plus separate real-database worker tests.
- `.dockerignore` excludes credentials, local environments, Git and test output.
  `scripts/verify_http.py` checks a real API/queue/worker/local HTTP receiver flow.

## Exact commands and results

Executed from the repository root. Values below belong exclusively to the new
local verification infrastructure, not application credentials.

```powershell
uv venv .venv --python D:/Programming/AuthFortress/.venv/Scripts/python.exe
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'
docker run -d --name webhook-verification-postgres -p 127.0.0.1:55433:5432 -e POSTGRES_DB=webhook_manager_test -e POSTGRES_USER=verification -e POSTGRES_PASSWORD=local-verification-only postgres:16-alpine
docker run -d --name webhook-verification-redis -p 127.0.0.1:56380:6379 redis:7-alpine
$env:DATABASE_URL='postgresql+asyncpg://verification:local-verification-only@127.0.0.1:55433/webhook_manager_test'
$env:REDIS_URL='redis://127.0.0.1:56380/0'
$env:CELERY_BROKER_URL=$env:REDIS_URL
$env:SECRET_KEY='local-verification-only-key-at-least-32-characters'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check
$env:TEST_DATABASE_URL=$env:DATABASE_URL
$env:TEST_REDIS_URL=$env:REDIS_URL
.venv/Scripts/python.exe -m pytest tests/unit tests/integration
.venv/Scripts/python.exe -m pytest tests/ --cov=src --cov-report=xml --cov-fail-under=80
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/verify_http.py
.venv/Scripts/python.exe -m mypy src/ --strict
docker compose -p webhook-verification -f docs/verification.compose.yml config --quiet
docker compose -p webhook-verification -f docs/verification.compose.yml build app
docker compose -p webhook-verification -f docs/verification.compose.yml up -d --no-deps --force-recreate app worker
.venv/Scripts/python.exe -m scripts.verify_http
docker compose -p webhook-verification -f docs/verification.compose.yml ps
docker compose -p webhook-verification -f docs/verification.compose.yml logs --tail 30 worker
docker run --rm webhook-verification:local python -c "from pathlib import Path; forbidden=['.env','.git','.venv']; assert not any((Path('/app')/name).exists() for name in forbidden); print('PASS: no .env, .git or .venv in /app')"
uvx --from bandit bandit -r src/ -ll
uvx --from pip-audit pip-audit --path .venv/Lib/site-packages --skip-editable
git diff --check
```

Results:

- Baseline unit/integration tests after safe harness conversion: 44 passed.
- Final complete suite: **62 passed**, coverage **83.05%**, exceeding CI's 80%.
  A second complete run also passed. One upstream 413 status-name deprecation
  warning remains; it does not fail the checks.
- Ruff: all checks passed. Strict Mypy: no issues in 87 source files.
- All three existing migrations upgraded on the empty verification database;
  `alembic check`: no new upgrade operations detected.
- Docker image builds; API/worker run without repository mounts. Image contains
  no `.env`, `.git` or `.venv` under `/app`.
- Real HTTP smoke passed: readiness, register/login and wrong password, API-key
  authentication, forged owner rejection, HMAC rejection/success, duplicate
  event identity, real Redis/Celery delivery, receiver 500 exhaustion,
  receiver-body/signature assertions, no credential headers, key revocation,
  Prometheus metrics. The smoke profile sets MAX_DELIVERY_ATTEMPTS=1 to avoid
  waiting through production retry delays. Five-attempt 500 and timeout paths
  are separately tested against the actual task and PostgreSQL with mocked HTTP.
- Test collection without TEST_DATABASE_URL fails before DB access with explicit
  RuntimeError. An ordinary application DATABASE_URL is never a fallback.
- Bandit: zero issues at all reported severity levels.
- pip-audit: `ecdsa 0.19.2`, advisory `PYSEC-2026-1325`, reported twice; no fix
  version listed. This is a transitive python-jose dependency. No jose/ecdsa
  imports exist in service code; reachability is not a clean dependency bill.
- `git diff --check` passed. No unrelated user edits were discarded.

The initial real smoke failed because the delivery module was unregistered;
the same smoke passes after the include fix. One immediate request after
container recreation raced API startup; the verification script now polls
readiness with a bounded timeout before testing the flow.

## Remaining findings and unverified gates

| ID | Severity | Evidence and required next action |
|---|---|---|
| WH-01 | High | `src/infrastructure/queue/tasks/deliver_webhook.py:108` sends arbitrary endpoint URLs. The local receiver demonstrates internal-host reachability. No URL/IP/network allowlist blocks private or metadata hosts. Define an egress policy before public deployment; the local verification receiver intentionally uses internal Docker networking. |
| WH-02 | High | `src/services/event_service.py:28` performs check-then-create, while `WebhookEventModel` has no unique `(source_id,idempotency_key)` constraint. Sequential duplicates are verified; concurrent exactly-once admission is not guaranteed. Requires forward migration and atomic conflict handling. |
| WH-03 | High | `src/infrastructure/queue/dispatcher.py` commits delivery rows before broker publication, and ingest schedules publication in an in-process background task. Broker failure/process crash can leave committed pending events with no queued task; duplicate ingest skips redispatch. Requires durable recovery/outbox and a broker-outage acceptance test. |
| WH-04 | Medium | Worker checks finalized status without locking the attempt across competing deliveries. Sequential repeated-task no-op is verified; concurrent sends and crash after receiver acceptance are not exactly-once guarantees. Receiver idempotency contract and claim/recovery strategy remain unverified. |
| WH-05 | Medium | Standalone login returns only user_id and requires a pre-existing API key for key creation. Smoke provisions the first key through the existing repository/service boundary. No public first-key onboarding or AuthFortress integration is proven. |
| WH-06 | Medium | Dependency audit above is unresolved. No blanket dependency upgrade was made. |
| WH-07 | Medium | `src/api/v1/dependencies/rate_limit.py` skips ingest limiting when X-API-Key is absent. Public HMAC ingestion requires no API key, so this route has no effective configured rate limit in that mode. |

Additional limitations:

- Tenant model/AuthFortress propagation/AgentHub/Telegram/provider integration
  are outside this independent service checkpoint.
- Migration downgrades were not executed: user safety rules require confirmation
  for destructive operations. No applied migration was edited.
- Public source authentication is optional when `Source.secret` is empty. Signed
  source verification is proven, but public deployment must require configured
  secrets through provisioning policy.
- Registration/login brute-force limits, password byte-limit failure handling,
  missing retry dispatch, delivery pagination, permanent 4xx retry policy and
  endpoint disable behavior remain existing acceptance gaps; they are not
  represented as verified functionality.
- Default CORS/trusted hosts, root Docker runtime/dev packages and lack of pinned
  dependencies need a deployment decision; only the disposable local profile
  was run.
- No production system, live Telegram receiver, VPS, TLS, load test, worker crash
  recovery, full outage recovery or dependency fix was tested.
- Fresh read-only reviewer outcome is recorded separately by the coordinating
  NexusCore task; no independent reviewer approval is claimed here yet.

## Final resume — 2026-10-04

Malformed non-ASCII HMAC signatures previously raised TypeError in compare_digest
and returned 500. Require exactly 64 lowercase hexadecimal characters before
constant-time comparison. Ten HMAC tests pass, including five malformed inputs.
Latest Docker image rebuilt and API/worker started successfully.

Independent reviewer reran the documented safe test environment:
`python -m pytest tests/ --cov=src --cov-report=term --cov-fail-under=80`: **67 passed**,
one upstream warning, 7.66s, **83.07% coverage**. `ruff check src tests scripts`
and `mypy src --strict` pass (87 files). `python -m scripts.verify_http` passes
against the rebuilt API and real worker, including ownership, HMAC, duplicate,
delivery, receiver 500, revocation and metrics. Exact full commands are retained
in NexusCore final verification report. No new patch defect remains in review.

Additional confirmed baseline findings: arbitrary endpoint URL userinfo/query
credentials reach raw URL logging in worker lines 131/166 (Medium); matching
subscriptions after the first 100 are not dispatched (Medium). These and the
existing publication/idempotency/egress/onboarding findings prevent full acceptance.
Critic confirmed these paths and rated concurrent non-idempotent worker delivery
High. No production exposure or migration downgrade was performed.
