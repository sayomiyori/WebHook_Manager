# Legacy local delivery hardening

Scope: close accepted-event loss, concurrent counters, unsafe retries, ambiguous
claims and SSRF without changing platform Telegram/AI contracts or dependencies.

Platform modes reject the unscoped legacy management, ingestion and global metric
surfaces. Standalone mode retains them. Platform bot/Telegram contracts remain
separate, authorized routes; historical unassigned data is never tenant-owned.

- Persist the event and every matching subscription intent in one transaction.
  A source/idempotency-key partial unique index serializes concurrent admission;
  duplicate admission returns the original event without new intents. Historical
  duplicate keys fail migration rather than being deleted or merged silently.
- Background dispatch only publishes saved intents; the existing scanner remains
  authoritative if the process dies before notification. No HTTP in admission.
- Endpoint counter changes serialize under a row lock after HTTP, while no lock
  spans network I/O. Redis is advisory; PostgreSQL determines circuit exhaustion.
- Manual retries accept only failed/exhausted attempts and create at most one
  successor per original attempt under a row lock. Active/pending/success claims
  return conflict, and superseded attempts cannot be scanned again.
- Authenticated owners may explicitly resolve only stale delivering claims with
  matching claim timestamp: confirmed delivered or confirmed not delivered.
  Persist actor, decision, time and a bounded operator reference atomically.
  Never resend automatically; confirmed-not-delivered becomes exhausted and a
  separate explicit retry is required. The worker cannot overwrite a resolution.
- Validate HTTP(S) URL syntax at configuration and at delivery. Reject userinfo,
  fragments and unsafe IPs. Resolve all addresses immediately before sending and
  connect to a checked numeric IP with original Host and TLS SNI. No environment
  proxy or redirects. Numeric trusted private origins are explicit test/operator
  configuration; metadata/link-local/multicast/reserved targets stay prohibited.
- Include a stable delivery ID for receiver/operator correlation. Raw user URLs,
  credentials and untrusted response text must not enter diagnostic logs.

Verification: real isolated PostgreSQL/Redis; admission rollback/concurrent
duplicate/crash-before-publication; simultaneous failures and success/failure;
manual retry races, claim resolution ownership/preconditions/no replay; blocked
literal/mixed DNS/rebinding/redirect/proxy targets and correct Host/SNI. Forward
migration up/down/up/check, full suite, Ruff, strict Mypy, fresh build/runtime
smoke and independent read-only adversarial/security review. Root and standalone
user data/volumes and dirty Compose paths are untouched during implementation.
