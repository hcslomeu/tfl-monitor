# 002 — Contracts-first parallelism

Status: accepted
Date: 2026-04-22

## Context

Four tracks (ingestion, dbt, API/agent, frontend) must progress in parallel
after TM-000 without coordination overhead. Without a shared source of
truth for interfaces, each track would invent its own understanding of
event shapes, endpoints, and database columns, then fight merge conflicts
later.

## Decision

All cross-track interfaces live in `contracts/`:

- `schemas/` — Pydantic v2 models for every Kafka event (tier-1 TfL raw +
  tier-2 internal Kafka wire format).
- `openapi.yaml` — OpenAPI 3.1 spec for every HTTP endpoint; TypeScript
  types and frontend mocks are generated from it.
- `sql/` — Postgres DDL for raw and reference tables.
- `dbt_sources.yml` — dbt sources derived from the DDL.

Any change under `contracts/` requires an ADR in `.claude/adrs/` and a
broadcast to every consumer. PR titles touching contracts must be prefixed
with `contract:`.

## Consequences

- **Pros**: a single edit point for any interface; downstream artefacts
  (TS types, dbt sources, Pydantic validators) regenerate mechanically;
  tracks can work against a known shape without waiting on each other.
- **Cons**: contract changes are heavier — they force ADRs and cross-track
  regeneration. That is the trade-off: we pay friction on change to buy
  parallelism during steady state.
