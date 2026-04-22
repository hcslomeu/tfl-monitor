# contracts/

Single source of truth for interfaces crossing service boundaries. **Changes
here require an ADR in `.claude/adrs/` and a broadcast to every consumer.**

- `schemas/` — Pydantic v2 models for each Kafka topic (producers and consumers agree here).
- `openapi.yaml` — OpenAPI 3.1 spec for every HTTP endpoint; frontend types generated from this file.
- `sql/` — Postgres DDL for raw and reference tables, applied in numeric order.
- `dbt_sources.yml` — dbt sources derived from the DDL; copied into `dbt/sources/tfl.yml`.
