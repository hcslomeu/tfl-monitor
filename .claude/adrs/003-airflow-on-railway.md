# 003 — Airflow on Railway in production

Status: superseded by [ADR 006](./006-aws-deploy.md) on 2026-05-15
Date: 2026-04-22

> **Superseded.** TM-A5 removed Airflow from production entirely
> (RAM budget on the shared Lightsail box does not fit Airflow's
> ~700 MB constant baseline). Periodic `dbt build` is invoked by
> host cron via `scripts/cron-dbt-run.sh`. Airflow stays in the
> local dev compose for the portfolio narrative. See ADR 006
> §Decision #4.

## Context

The project needs a batch orchestrator for nightly dbt runs and static
TfL data ingestion (reference lines, stations). The portfolio signal
value of running real Airflow is high — it is the de facto industry
standard for data engineering roles. Cloud-managed Airflow (MWAA,
Composer, Astronomer) is expensive for a portfolio project.

## Decision

Deploy Airflow 2.10+ on Railway with LocalExecutor, sharing the same
PostgreSQL instance (Supabase) as the warehouse. Target cost ≈ £5/month.

## Consequences

- **Pros**: authentic Airflow deployment, LocalExecutor handles the DAG
  volume here (≤ 10 tasks/run), cost fits inside a portfolio budget,
  single Postgres keeps infrastructure small.
- **Cons**: LocalExecutor runs tasks in-process, so a heavy task can
  saturate the Railway container. Acceptable at this scale. If the work
  ever justifies CeleryExecutor, a migration is straightforward.
