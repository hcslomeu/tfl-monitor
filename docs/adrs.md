# Architectural decisions

ADRs (Architecture Decision Records) live under
[`.claude/adrs/`](https://github.com/hcslomeu/tfl-monitor/tree/main/.claude/adrs).
This page is a curated index — the authoritative text is in the repo so it
travels with `git log`.

| ID | Title | Status | Why it exists |
|----|-------|--------|---------------|
| 001 | [Redpanda over Apache Kafka](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/001-redpanda-over-kafka.md) | Accepted | Single-binary Kafka API; identical local ↔ prod surface |
| 002 | [Contracts-first parallelism](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/002-contracts-first.md) | Accepted | Two-tier Pydantic schemas + OpenAPI as the single source of truth |
| 003 | [Airflow on Railway](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/003-airflow-on-railway.md) | Superseded by 006 | Original deploy plan for Airflow on Railway free tier |
| 004 | [Logfire + LangSmith split](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/004-logfire-langsmith-split.md) | Accepted | App vs LLM observability split — what goes where, why |
| 005 | [Raw-table defaults](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/005-raw-table-defaults.md) | Accepted | DB-side `gen_random_uuid()` + `now()` defaults on `raw.*` |
| 006 | AWS Bedrock + single-EC2 deploy | Pending (TM-A5) | Replaces 003: $100 AWS credit + Bedrock collapses to one box |

## When does work need an ADR?

If a PR does any of the following, it must ship an ADR alongside the diff:

!!! warning "Mandatory ADR triggers"
    - **Adds or modifies anything under `contracts/`** — schemas, OpenAPI,
      DDL, dbt sources mirror.
    - **Substitutes a locked tech-stack choice** — e.g. swapping Redpanda for
      RabbitMQ, or LangGraph for LangChain agents.
    - **Crosses a track boundary** — e.g. a D-track WP touching `src/ingestion/`
      gets an ADR §"Consequences" entry declaring the cross-touch.
    - **Adds a new long-running deployment artefact** — service in compose,
      Airflow DAG, GitHub Actions workflow.

The ADR template lives in
[`.claude/adrs/`](https://github.com/hcslomeu/tfl-monitor/tree/main/.claude/adrs)
and follows the standard Context / Decision / Consequences shape.

## Why ADRs over wiki pages

Two reasons:

1. **They travel with git history.** A future reader cloning the repo can read
   the entire decision log without internet access.
2. **They are reviewable.** ADRs land via PRs and get reviewed like code, so
   the decision and the diff that implements it ship together.
