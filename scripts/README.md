# scripts/

One-off Python utilities supporting development. Excluded from Mypy
(`pyproject.toml` `tool.mypy.exclude = ["scripts/"]`) — the type discipline
kicks in at the package boundary, not in throwaway helpers.

## Contents

| Script | Purpose |
|--------|---------|
| [`fetch_tfl_samples.py`](./fetch_tfl_samples.py) | Pulls live TfL Unified API responses into `tests/fixtures/tfl/`. Re-run when TfL changes a schema. |

## When to re-run it

```bash
# After TfL change a response shape (rare):
uv run python scripts/fetch_tfl_samples.py
```

`fetch_tfl_samples.py` reads the TfL `app_key` from `.env`. The captured
fixtures are committed under `tests/fixtures/tfl/` so unit tests do not need
network access.

## Why these are scripts and not packages

They are run **at most a few times a year** and have no external consumers.
A Typer CLI or click subcommand would add dependencies and indirection for a
problem that does not exist (CLAUDE.md *Principle #1*).
