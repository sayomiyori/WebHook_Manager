---
# ADR-003: Celery for webhook delivery

## Status
Accepted

## Date
2026-03-18

## Context
We needed reliable asynchronous webhook delivery with retries and observability; options considered were arq and rq, but they did not meet our maturity/monitoring expectations.

## Decision
We chose Celery + Redis as the delivery queue because it provides mature retry mechanics, operational tooling, and fits our "fire-and-forget" delivery model.

## Consequences
### Positive
- Mature ecosystem for retries and worker monitoring, suitable for delivery pipelines.
### Negative / tradeoffs
- Heavier setup/maintenance than lightweight alternatives like arq.
---
