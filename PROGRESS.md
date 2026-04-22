# PROGRESS

Current state of work packages. Update the status column as WPs land.

| Phase | WP | Title | Track | Status | Notes |
|---|---|---|---|---|---|
| 0 | TM-000 | Contracts and scaffold | — | ✅ 2026-04-22 | Scaffold, contracts, tier-1/tier-2 schemas, fixtures fetched |
| 1 | TM-A1 | Docker Compose + Postgres + Redpanda + Airflow | A-infra | ⬜ | |
| 1 | TM-B1 | Async TfL client + fixtures | B-ingestion | ⬜ | |
| 2 | TM-C1 | dbt scaffold | C-dbt | ⬜ | |
| 2 | TM-D1 | FastAPI skeleton + Logfire wiring | D-api-agent | ⬜ | |
| 3 | TM-B2 | `line-status` producer | B-ingestion | ⬜ | |
| 3 | TM-B3 | `line-status` consumer | B-ingestion | ⬜ | |
| 3 | TM-C2 | dbt staging + first mart | C-dbt | ⬜ | |
| 3 | TM-D2 | Wire endpoints to Postgres | D-api-agent | ⬜ | |
| 3 | TM-E1 | Next.js + claude.design + Network Now | E-frontend | ⬜ | |
| 4 | TM-B4 | arrivals + disruptions topics | B-ingestion | ⬜ | |
| 4 | TM-C3 | Remaining marts + tests + exposures | C-dbt | ⬜ | |
| 4 | TM-D3 | Remaining endpoints | D-api-agent | ⬜ | |
| 4 | TM-E2 | Disruption Log view | E-frontend | ⬜ | |
| 5 | TM-A2 | Airflow DAGs | A-infra | ⬜ | |
| 5 | TM-D4 | RAG ingestion: Docling → Pinecone | D-api-agent | ⬜ | |
| 6 | TM-D5 | LangGraph agent (SQL + RAG + Pydantic AI) | D-api-agent | ⬜ | |
| 6 | TM-E3 | Chat view with SSE | E-frontend | ⬜ | |
| 7 | TM-A3 | Supabase provisioning | A-infra | ⬜ | |
| 7 | TM-A4 | Redpanda Cloud | A-infra | ⬜ | |
| 7 | TM-A5 | Railway deploy (Airflow + API + agent + workers) | A-infra | ⬜ | |
| 7 | TM-E4 | Vercel deploy | E-frontend | ⬜ | |
| 7 | TM-F1 | README polish + demo video + live URL | F-polish | ⬜ | |

## TM-000 notes

Mid-execution deviations, captured as ADRs or inline footnotes:

- `[tool.uv.scripts]` in the original spec is not a real uv feature;
  replaced by `taskipy` in `[tool.taskipy.tasks]` with a slim Makefile
  for system orchestration.
- Next.js generator produced v16.2.4 (spec locked at 15); kept v16
  because current `create-next-app` defaults to it and v16 is
  backward-compatible for the app-router scaffold used here.
- shadcn CLI flow changed: `--base=radix --preset=nova` matches the
  legacy "Default / Slate / CSS variables=Yes" intent and avoids
  interactive prompts.
- Contracts split into two tiers: tier-1 `tfl_api` for raw TfL
  responses (camelCase, optional-heavy) and tier-2 Kafka events
  (snake_case, frozen, per spec §5.1). See ADR 002.
