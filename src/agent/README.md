# src/agent/

Legacy LangGraph package, kept for parity with earlier WPs. **The active
agent lives at [`src/api/agent/`](../api/agent)** — TM-D5 moved the graph
under the API package so the FastAPI lifespan can compile it once and cache
it on `app.state.agent`.

## Why this directory still exists

- A small number of tests under `tests/agent/` import `agent.observability`
  for span-namespace assertions. Removing the package would churn the test
  paths in a separate WP.
- `pyproject.toml`'s wheel target lists `src/agent` so removing it is a
  packaging change that needs an ADR.

## What's inside

```text
src/agent/
├─ __init__.py
├─ graph.py             # legacy graph factory — used only by test fixtures
└─ observability.py     # Logfire span-namespace constants
```

## Migration path

| When | Action |
|------|--------|
| TM-A5 PR-1 (Bedrock swap) | Validate that no production code path imports from `src/agent`. |
| Post-TM-A5 | Delete `src/agent/`, update `pyproject.toml` wheel target, migrate test fixtures to `src/api/agent`. |

This README will be removed alongside the directory in that follow-up PR.
