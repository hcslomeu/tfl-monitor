# TM-B1 — Research (Phase 1)

Read-only exploration. Track: **B-ingestion**. Linear issue: **TM-4** (open).

Objective from `SETUP.md` §7.3: "Implement the async TfL API client and generate real response fixtures."

Architectural context (`ARCHITECTURE.md`): the ingestion client lives at
`src/ingestion/tfl_client`, speaks to `https://api.tfl.gov.uk` over async
`httpx`, and is responsible for tier-1 → tier-2 normalisation ("TM-B1+").

## Scope boundary

Allowed paths (user-declared for this WP):
`src/ingestion/`, `tests/ingestion/`, `tests/fixtures/tfl/`.

Frozen (no edits): `contracts/schemas/tfl_api.py` and
`contracts/schemas/{arrivals,line_status,disruptions,common}.py`.

Out of track (do NOT touch without an ADR): `contracts/`,
`scripts/fetch_tfl_samples.py`, existing `tests/fixtures/*.json`,
`tests/test_contracts.py`.

## What already exists

### Contracts — frozen

`contracts/schemas/tfl_api.py` (tier-1, camelCase) exposes:

| Model | Source endpoint |
|---|---|
| `TflLineResponse` | `/Line/Mode/{modes}/Status` |
| `TflArrivalPrediction` | `/StopPoint/{id}/Arrivals` |
| `TflDisruption` | `/Line/Mode/{modes}/Disruption` |

Nested: `TflLineStatusItem`, `TflLineStatusDisruption`,
`TflValidityPeriod`. All `frozen=True`, `extra="ignore"`, `to_camel`
aliasing. `contracts/schemas/__init__.py` re-exports the tier-1 names at
package root.

Tier-2 Kafka events (snake_case, TOPIC_NAME attribute on each envelope):
`LineStatusEvent` (`line-status`), `ArrivalEvent` (`arrivals`),
`DisruptionEvent` (`disruptions`) with their respective `*Payload`
classes. `test_contracts.py` asserts tier-1 fixtures parse and tier-2
roundtrips hold; TM-B1 must not break these.

### Ingestion scaffold — empty

```text
src/ingestion/
  __init__.py          (0 bytes)
  tfl_client/
    __init__.py        (0 bytes)   ← target for the new client
  producers/           (placeholder for TM-B2)
  consumers/           (placeholder for TM-B3)
```

Package is declared in `pyproject.toml` under `[tool.hatch.build.targets.wheel].packages`.

### Existing fixtures

Committed under `tests/fixtures/` (NOT `tfl/`):

| File | Endpoint captured | Size |
|---|---|---|
| `line_status_sample.json` | `/Line/Mode/tube,elizabeth-line,dlr,overground/Status` | 34 KB |
| `arrivals_sample.json` | `/StopPoint/940GZZLUOXC/Arrivals` | 17 KB |
| `disruptions_sample.json` | `/Line/Mode/tube/Disruption` | 7 KB |

These are real TfL responses (confirmed by `$type` envelopes visible in
the JSON) and are already exercised by `tests/test_contracts.py`
against the tier-1 models.

### Fetch helper — `scripts/fetch_tfl_samples.py`

Synchronous `httpx.Client`, 30-second timeout, writes to
`tests/fixtures/<filename>`. Endpoints and `app_key` auth pattern
documented there. **Not** in B1's allowed paths.

### Dependencies present

`httpx>=0.28`, `pydantic>=2.9`, `python-dotenv>=1.0`,
`pytest-asyncio>=0.24`. No `respx`, no retry library in the root
`pyproject.toml`.

### Env

`.env.example`: `TFL_APP_KEY=your_tfl_key_here`.

## Current state verification

- `src/ingestion/tfl_client/__init__.py` empty → nothing to run.
- `uv run task test` covers `tests/test_contracts.py` and
  `tests/test_health.py`; no ingestion tests today.

## Design surface for TM-B1

Strictly research — the plan will make the actual choices.

### Client shape (candidates)

A small `TflClient` class wrapping `httpx.AsyncClient`:

- Async context manager (`__aenter__`, `__aexit__`).
- Base URL `https://api.tfl.gov.uk`; `app_key` as query param
  (existing pattern) or `app_key`/`app_id` header (newer TfL pattern
  — query still works). Existing `fetch_tfl_samples.py` uses query.
- Three coroutine methods returning tier-1 typed objects:
  - `fetch_line_statuses(modes: Iterable[str]) -> list[TflLineResponse]`
  - `fetch_arrivals(stop_id: str) -> list[TflArrivalPrediction]`
  - `fetch_disruptions(modes: Iterable[str]) -> list[TflDisruption]`
- Parsing: `TypeAdapter(list[Tfl...]).validate_python(resp.json())`
  (cheaper than per-item `model_validate` loops).

### Retry / backoff

TfL free tier rate limit: 500 req/min. Failure modes to design for:

- `HTTP 429 Too Many Requests` — respect `Retry-After` header.
- `HTTP 5xx` — bounded exponential backoff.
- `httpx.TimeoutException` / `httpx.TransportError` — retry bounded.
- Everything else (401, 400, 404) — raise immediately; no retry value.

Stdlib-friendly approach: small in-house loop (~20 lines) following
CLAUDE.md rule 7 (no custom CLI / exotic policy library without cause).
`tenacity` would be idiomatic but it is a new dep → ADR territory.

### Normalisation tier-1 → tier-2

ARCHITECTURE.md states normalisation is the ingestion client's job
starting in "TM-B1+". Choices:

- (a) Land normalisation now — three small adapters mapping
  `TflLineResponse → LineStatusPayload`, etc. Self-contained in
  `src/ingestion/tfl_client/normalise.py` and unit-tested against
  fixtures.
- (b) Defer to TM-B2, where the producer turns tier-1 into tier-2 on
  the way to Kafka. Keeps TM-B1 smaller but makes TM-B2 responsible
  for semantic translation *and* Kafka wiring.

### Fixtures layout

User's allowed path is `tests/fixtures/tfl/`. Existing fixtures live at
`tests/fixtures/` root and drive `tests/test_contracts.py`, which is out
of track. Options:

- (a) Leave the existing three JSONs untouched; generate additional /
  richer fixtures under `tests/fixtures/tfl/` dedicated to ingestion
  tests (e.g. one file per endpoint keyed by stop/mode parameter).
- (b) Move existing JSONs into `tests/fixtures/tfl/` — requires
  editing `tests/test_contracts.py` and `scripts/fetch_tfl_samples.py`,
  both out of track. Blocks on an ADR or a scope exception from the
  author.

### Tests

Layout `tests/ingestion/test_tfl_client.py` or one file per endpoint.
Transport: `httpx.MockTransport` (already available, no new dep). Cover:

- Happy path — fixture bytes → tier-1 models parsed.
- `app_key` propagation — assert query param present on every request.
- Retry policy — 429 with `Retry-After` retried; 500 retried;
  max-attempts enforced; 401 raised immediately.
- Timeout surfaces via `httpx.TimeoutException`.

If normalisation lands inside B1, add `tests/ingestion/test_normalise.py`.

## Gap analysis / what the WP must deliver (not prescriptive)

| # | Area | Minimum bar |
|---|---|---|
| B1.1 | Async client module under `src/ingestion/tfl_client/` | Three endpoint methods, tier-1 typed returns, async context manager |
| B1.2 | Auth + config | Reads `TFL_APP_KEY` from env; fails loud if missing |
| B1.3 | Retry policy | 429 / 5xx / transport errors — bounded attempts; respects `Retry-After` |
| B1.4 | Fixtures | Real TfL responses under `tests/fixtures/tfl/` covering the three endpoints (possibly overlapping with existing fixtures) |
| B1.5 | Tests | `tests/ingestion/test_tfl_client.py` covering happy path, retry, auth |
| B1.6 | Normalisation (optional) | Tier-1 → tier-2 adapters if we decide to land them here |

## Key documents reviewed

- `ARCHITECTURE.md` — confirms `src/ingestion/tfl_client` role.
- `contracts/schemas/tfl_api.py`, `contracts/schemas/__init__.py`.
- `contracts/schemas/{arrivals,line_status,disruptions,common}.py`
  (read-through — tier-2 shapes known, frozen).
- `scripts/fetch_tfl_samples.py` — endpoint list, auth pattern.
- `tests/test_contracts.py`, `tests/fixtures/*.json`.
- `src/ingestion/__init__.py`, `src/ingestion/tfl_client/__init__.py`.
- `.env.example`, `pyproject.toml`, `Makefile`.
- `CLAUDE.md` — Pydantic boundaries, lean defaults, no custom retry
  policies "before a real error exists"; zero-trust security.
- `AGENTS.md` — PR rules (no hardcoded secrets; ingestion tests must
  use fixtures, never live API).

## Open questions for the planning phase

1. **Fixture layout.** Which of (a) "add-alongside under `tfl/`" or
   (b) "move existing into `tfl/` + out-of-track edits" does the
   author prefer? Recommendation: (a) — avoids scope leak.
2. **Normalisation inclusion.** Include tier-1 → tier-2 normalisation
   in TM-B1 or defer to TM-B2? Recommendation: include — ARCHITECTURE
   already earmarks it here and it unblocks B2.
3. **Retry implementation.** Hand-rolled loop (lean) or `tenacity`
   (idiomatic, new dep + ADR)? Recommendation: hand-rolled ≤30 lines,
   co-located in the client module. New deps invite AGENTS.md §"PR
   rules — Dependencies" scrutiny.
4. **Async test wiring.** `pytest-asyncio` with `asyncio_mode = "auto"`
   is already enabled in `pyproject.toml`; confirm we keep it.
5. **Request concurrency.** Do we need a shared `httpx.AsyncClient` in
   the class (one connection pool) and explicit `.aclose()` in tests?
   Yes — standard pattern; pose for confirmation in the plan.
