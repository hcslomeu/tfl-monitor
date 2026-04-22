# 003 — Airflow on Railway in production

Status: accepted
Date: 2026-04-22

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
