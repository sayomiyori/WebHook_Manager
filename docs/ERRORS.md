# Error log

## 2026-10-09: Delivery success, pagination and subscriptions

- Redis reset failure after a committed HTTP success entered the retry handler
  and resent the webhook. Commit success and all later side effects outside the
  delivery failure handler. Regressions cover RedisError and a late Celery soft
  timeout followed by redelivery: one HTTP request, durable success preserved.
- Delivery history silently discarded cursor/limit. Pass both to the repository.
- Event matching only read the first 100 subscriptions. Traverse existing cursor
  pages; a 205-subscription regression verifies the final page is included.
- Use DELIVERY_TIMEOUT_SECONDS rather than a hardcoded HTTP timeout. Logs use
  endpoint UUID, static exception classes and suppressed credential-bearing HTTP
  transport logs instead of raw destination URLs/network exception text.
- Full suite: 320 passed, coverage 85.02%; Ruff and strict Mypy passed. Independent
  review approved. Legacy concurrent claims, ambiguous-send recovery and SSRF
  restrictions remain separate work; this is not an exactly-once guarantee.
- Tracked generated egg-info still advertised removed python-jose dependencies.
  Stop tracking those already ignored build artifacts; refresh local editable
  metadata and remove unused python-jose/ecdsa. `uv pip check`, pip-audit and a
  repeated 320-test run pass. The current image already excluded these packages.

## 2026-10-03 — Test database escape and destructive cleanup

Symptom: test bootstrap overwrote explicit DATABASE_URL with ordinary `.env`
values and truncated every service table before/after tests.
Cause: manual environment loader plus `_truncate_all` fixture.
Fix: require TEST_DATABASE_URL ending `_test` and explicit TEST_REDIS_URL;
transaction rollback/savepoints and migrated schema replace table cleanup.
Detection: collection without TEST_DATABASE_URL raises RuntimeError before DB
access. Full PostgreSQL suite passes twice without TRUNCATE/DROP.

## 2026-10-03 — Management API owner impersonation

Symptom: endpoints/events/subscriptions/deliveries could be read or modified
without API-key authentication, often by supplying another owner's UUID.
Cause: routers trusted request owner/source/resource IDs independently of identity.
Fix: existing active API-key dependency on management routes, identity-bound
owner parameters and source/endpoint/event/subscription ownership checks.
Detection: regression requests across all management resource groups return
401 without credentials and 403 for another authenticated owner.

## 2026-10-03 — Celery discarded delivery tasks

Symptom: real API ingestion succeeded but the worker logged `Received
unregistered task of type 'deliver_webhook'` and discarded the message.
Cause: worker app did not include/import the task module; eager tests imported it
implicitly and hid the deployment failure.
Fix: explicit task-module include in the Celery application.
Detection: worker include regression and real HTTP → Redis → worker → controlled
receiver smoke pass, including a 500 receiver failure.

## 2026-10-03 — Credentials and transport headers forwarded

Symptom: ingestion persisted all incoming headers; worker reused them as outgoing
receiver headers, including API keys, authorization/cookies, host/length/signature.
Cause: unfiltered copies at both ingress and delivery boundaries.
Fix: common credential/hop-by-hop sanitizer at ingress, direct event creation,
and worker delivery (including previously stored events); regenerated signature.
Detection: worker tests seed legacy sensitive headers and assert they are absent
at HTTP boundary; real receiver asserts no API-key/authorization/cookie header.

## 2026-10-03 — Ambiguous public source slug

Symptom: two owners could create the same slug; global lookup selected the first
source for a public webhook route with no owner context.
Cause: owner-scoped uniqueness and global `first()` lookup.
Fix: global lookup accepts only an unambiguous single source, otherwise fails
closed with 404. Owner-scoped source contracts and migrations remain unchanged.
Detection: regression creates the same slug under two owners and verifies 404.
# 2026-10-04 — Malformed HMAC returned 500

Non-ASCII supplied signature reached `hmac.compare_digest` as a string and raised
TypeError. Validate exact lowercase hexadecimal SHA256 length first. Regression:
five malformed values reject without exceptions; full suite 67 passed.

## 2026-10-06 — Telegram chat type and inactive tenant classification

Malformed chat.type arrays/objects raised TypeError during set membership and
returned 500. Validate the type before membership; HTTP regressions require a
sanitized 422. Canonical inactive tenant status was treated as issuer outage503,
causing publication retry instead of cancellation. Distinguish inactive403 from
invalid/unavailable issuer responses; real database worker tests assert cancelled
without AgentHub calls.

## 2026-10-06 — Interrupted webhook setup status

Expired configuring claims remained configuring indefinitely. Read-time SQL
projection now reports unknown using PostgreSQL clock_timestamp, preserving the
stored claim for fenced retry. HTTP regression seeds an expired claim and checks
the bot view; schema and the applied migration remain unchanged.

## 2026-10-06 — Retry reported a different webhook URL

After an operator origin change, retry correctly reused the persisted URL but
returned the new computed origin in its response. Both dry-run and apply now
report the prepared URL, consistent with v1's no-URL-replacement contract.
Regression changes the origin after an ambiguous setup and checks the dry-run,
provider request and success response against the original stored URL.

## 2026-10-08 — Explicit webhook relocation after an origin change

The original retry contract deliberately retained the stored origin, so a new
tunnel/domain could not replace it through the API. Add opt-in `replace_url`
with a side-effect-free preview and the existing owner/tenant authorization,
per-bot claim and ambiguous-result handling. Preserve the secret and default
retry behavior. Regressions cover unchanged defaults, preview without writes,
replacement/idempotency, definite and ambiguous failures, concurrent replacement,
invalid input and unauthorized/cross-tenant requests. No schema migration needed.

## 2026-10-06 — Security CI audited tools instead of the application

The legacy safety check command exited64; the job installed only Safety/Bandit,
not project dependencies. Install the project and use pip-audit after Bandit.
Remove unused python-jose (including its vulnerable ecdsa dependency); declare
cryptography directly because existing bot/webhook encryption imports Fernet.
Keep dependency audit failures blocking; no advisories are ignored.

## 2026-10-06 — API-key usage update raced with revocation

Background usage tracking used ORM merge and refreshed after commit. Concurrent
revocation could recreate the deleted credential or fail after the HTTP response.
Use UPDATE RETURNING, materialize before commit, and treat a missing key as a
background no-op. PostgreSQL regression deletes the key through an independent
session before the stale update and verifies that authentication remains denied.

## 2026-10-06 - Forward answer migration dependency order

The first empty-test-database upgrade of the new answer migration failed because
Alembic placed the ingress scope unique constraint after the referencing table.
The unpublished migration now creates the constraint before the answer FK and
drops it after the answer table during rollback. The isolated approved
3cc3bb772105 -> 9a3c012bd7ef -> 3cc3bb772105 roundtrip and schema check passed.
No previously published migration was changed.

## 2026-10-06 - Inactive bot obtained a send claim

The first sender implementation checked bot activation only after claiming an
answer. A negative test reproduced attempts=1 for an already inactive bot.
Claims now lock and check the canonical bot before claiming the answer; inactive
records become cancelled without consuming an attempt. Bot-before-answer lock
order matches admission and send-start. Fresh issuer/bot checks still run before
the committed external-effect marker.
