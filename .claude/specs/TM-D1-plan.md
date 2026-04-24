# TM-D1 — Implementation plan (Phase 2)

Source: `TM-D1-research.md` + author decision on `2026-04-23` (close
scope gaps with a concrete polish PR, option G1 + G2 + G4 from
research).

## Summary

TM-000 shipped the FastAPI skeleton with 501 stubs and a Logfire wiring
that matches `CLAUDE.md` §"Observability architecture" word-for-word.
TM-D1 closes the WP by locking that contract against drift and
correcting one real bug: the CORS allow-list is missing the production
Vercel origin quoted in `contracts/openapi.yaml`.

Deliverables:

1. **G1** — parametrised test asserting every non-`/health` route
   returns `501` with its owning-WP hint.
2. **G2** — drift test asserting every `operationId` in
   `contracts/openapi.yaml` has a matching FastAPI route, and vice
   versa.
3. **G4** — add `https://tfl-monitor.vercel.app` to the CORS
   allow-list.

No changes under `contracts/` (no ADR needed). All edits live under
`src/api/` + `tests/api/`.

## Execution mode

- **Author of change:** agent-team member (worktree-isolated). Team
  name: `tfl-phase-1-2`. Member name: `tm-d1`.
- **Branch (inside worktree):** `feature/TM-D1-api-stubs-drift-test`.
- **PR title:** `feat(api): TM-D1 lock 501 stubs + drift test + prod CORS origin (TM-6)`.
- **PR body:** references `Closes TM-6`, references CLAUDE.md rule it
  enforces, lists the three deliverables.

## What we're NOT doing

- Not implementing any of the stubbed routes — those belong to TM-D2 /
  TM-D3 / TM-D5.
- Not touching `contracts/openapi.yaml` — tier-1 contract, frozen;
  drift test *reads* it, does not edit it.
- Not adding custom metrics / tracing — Logfire is enough (CLAUDE.md
  §"Anti-patterns — Over-observing").
- Not introducing `Settings(BaseSettings)` for the API — YAGNI;
  revisit when >= 15 env vars (CLAUDE.md rule 5).
- Not wiring real `/health` dependency checks — TM-D2 when Postgres
  arrives.
- Not changing the existing `tests/test_health.py` — only adding new
  tests under `tests/api/`.

## Sub-phases

### Phase 3.1 — CORS allow-list (G4)

Edit `src/api/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tfl-monitor.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Both origins are explicit — no `*`. Matches the value documented at
`contracts/openapi.yaml` line 13.

### Phase 3.2 — 501 stub lock (G1)

Create `tests/api/__init__.py` (empty) and `tests/api/test_stubs.py`.

- Parametrise across the 7 stubbed routes.
- For GET routes, hit them via `TestClient.get(path)`.
- For POST `/api/v1/chat/stream`, use `TestClient.post(path, json={...})`
  with a minimal body honouring `ChatRequest` shape (`thread_id`,
  `message`). Even when the body is valid, the handler must still
  return 501.
- For path-param routes, supply placeholders (`line_id="victoria"`,
  `stop_id="dummy"`, `thread_id="t-1"`).
- Assert `response.status_code == 501`.
- Assert `response.json()["detail"]` starts with `"Not implemented"`.
- Assert the WP hint present (e.g. `"TM-D2"`, `"TM-D3"`, `"TM-D5"`).

### Phase 3.3 — Route/OpenAPI drift test (G2)

Extend `tests/api/test_stubs.py` (or a sibling `test_operation_ids.py`)
with two assertions driven by the existing `openapi-spec-validator` dev
dep for YAML loading (already in `pyproject.toml`; if it does not
expose a YAML loader directly, parse with PyYAML — check first, avoid
a new runtime dep):

- **Spec → app:** every `operationId` declared in
  `contracts/openapi.yaml` exists as a registered route on `app` (by
  looking at `app.routes` for `APIRoute` instances and comparing
  `route.operation_id`).
- **App → spec:** every `APIRoute` on `app` (excluding FastAPI's
  built-in `/openapi.json`, `/docs`, `/redoc` if present) has a
  matching `operationId` entry in the spec.

If `pyyaml` is not already a transitive dep, prefer using
`openapi-spec-validator`'s loader (`openapi_spec_validator.readers`)
or add `pyyaml` to the `dev` group — flag the cost in the PR if it
turns out to require a new dep (CLAUDE.md §"Anti-patterns — YAGNI").

### Phase 3.4 — Verification gate

Before opening the PR:

```bash
uv run task lint          # ruff + ruff format + mypy strict
uv run task test          # includes new tests/api/*
uv run bandit -r src      # HIGH severity only
make check                # broader; runs dbt-parse + TS lint too
```

All must exit 0. If mypy strict complains about `app.routes` typing,
cast to `Iterable[APIRoute]` explicitly rather than loosening strict
config (CLAUDE.md §"Anti-patterns — Security shortcuts" spirit).

### Phase 3.5 — PR

Open PR from `feature/TM-D1-api-stubs-drift-test` targeting `main`.

PR body (English):

- **Summary** — 3 bullets on G1/G2/G4.
- **Why** — cites TM-D1 spec, quotes the relevant CLAUDE.md rules
  (observability + security).
- **Out of scope** — real route implementations (TM-D2/D3/D5).
- **Test plan** — `uv run task test` + `make check`.
- **Closes TM-6**.

## Success criteria

- [ ] `tests/api/test_stubs.py` parametrised across 7 routes, all
  assertions green.
- [ ] OpenAPI drift test green (both directions).
- [ ] `src/api/main.py` CORS allow-list contains both local and Vercel
  origins.
- [ ] `uv run task lint` + `uv run task test` + `uv run bandit -r src`
  + `make check` all exit 0.
- [ ] PR opened with `Closes TM-6` in the body.
- [ ] `PROGRESS.md` TM-D1 row updated to ✅ with the completion date.

## Open questions (resolved during planning)

1. **G2 implementation — runtime YAML parser.**
   Resolution: use `openapi-spec-validator`'s built-in loader (already
   present). If unusable, add `pyyaml` to the `dev` dependency group
   and justify in the PR body. Do not add `pyyaml` to runtime.
2. **Should the drift test be marked `@pytest.mark.integration`?**
   Resolution: no. It parses a static YAML file — no external services
   needed — so it belongs in the default (fast) test run.
3. **Should `POST /api/v1/chat/stream` 501 test include SSE headers?**
   Resolution: no. 501 is returned before any SSE framing; asserting
   `text/event-stream` headers would accidentally constrain TM-D5.
