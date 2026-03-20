---
# ADR-002: Clean Architecture

## Status
Accepted

## Date
2026-03-18

## Context
We needed strong separation between business logic and infrastructure (DB, Redis, HTTP transport) to keep services testable and support swapping adapters.

## Decision
We adopted a Clean Architecture structure with domain entities, application services, and infrastructure implementations, using repository interfaces and FastAPI Depends for wiring.

## Consequences
### Positive
- High testability: services can run with fake in-memory repositories.
### Negative / tradeoffs
- More boilerplate up front (interfaces, mappers, and wiring).
---
