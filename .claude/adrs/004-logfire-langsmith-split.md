# 004 — Logfire for app + LangSmith for LLM

Status: accepted
Date: 2026-04-22

## Context

Observability needs split across two domains:

- **Application + infra**: FastAPI request latency, Postgres queries,
  HTTP client behaviour, Kafka consumer lag. Needs OpenTelemetry-native
  integration.
- **LLM + agent**: routing decisions, retrieval chunks, tool calls,
  token usage. Needs LLM-specific context captured automatically.

Self-hosting Prometheus + Grafana + OpenTelemetry collector would add two
Docker services, a metrics store, a dashboard product, and alerting
configuration — none of which carry portfolio signal value.

## Decision

Use two hosted tools, strictly separated:

- **Logfire** instruments FastAPI, `httpx`, and `psycopg`. Reads
  `LOGFIRE_TOKEN` from env; absent token means no-op mode (fine in dev).
- **LangSmith** receives LangGraph and Pydantic AI traces via its
  environment integration. Set `LANGSMITH_TRACING=true`,
  `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`.

Both free tiers cover this project. No custom metrics wrapper, no
Prometheus, no Grafana, no OpenTelemetry collector, no self-hosted
telemetry stack.

## Consequences

- **Pros**: zero ops overhead for observability, purpose-specific tooling
  on each domain, no secondary services in docker-compose.
- **Cons**: two dashboards instead of one; neither is portable outside
  its vendor. We accept this because the traces are also cheap to replay
  if either vendor disappears, and the saved effort on self-hosted
  observability is substantial.
