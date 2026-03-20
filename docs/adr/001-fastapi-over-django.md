---
# ADR-001: FastAPI over Django/Flask

## Status
Accepted

## Date
2026-03-18

## Context
We needed an async-first API service with lightweight implementation and auto OpenAPI docs; Django/Flask would require more effort to match the async request patterns and schema generation.

## Decision
We chose FastAPI to keep the API layer small while leveraging dependency injection, validation, and automatic OpenAPI for integration testing.

## Consequences
### Positive
- Async-first request handling with built-in OpenAPI documentation and validation.
### Negative / tradeoffs
- Smaller ecosystem than Django for certain "batteries-included" workflows.
---
