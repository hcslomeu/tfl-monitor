# TM-B1 — Implementation plan (Phase 2)

Source: `TM-B1-research.md` + author decisions on `2026-04-23`:

- **Q2 — fixture layout:** add-alongside under `tests/fixtures/tfl/`;
  do not move the existing `tests/fixtures/*_sample.json` (out of
  track).
- **Q3 — normalisation:** include tier-1 → tier-2 normalisation in
  TM-B1 (per ARCHITECTURE.md placement at "TM-B1+").
- **Q4 — retry:** hand-rolled bounded loop inside the client module,
  no new dependency.

## Summary

Implement the async TfL Unified API client under
`src/ingestion/tfl_client/`, ship real fixtures under
`tests/fixtures/tfl/`, land the tier-1 → tier-2 normalisation layer so
TM-B2's producer only has to handle wire + Kafka concerns, and cover
the surface with `tests/ingestion/`. No Kafka, no `contracts/` edits.

## Execution mode

- **Author of change:** agent-team member (worktree-isolated). Team
  name: `tfl-phase-1-2`. Member name: `tm-b1`.
- **Branch (inside worktree):** `feature/TM-B1-async-tfl-client`.
- **PR title:** `feat(ingestion): TM-B1 async TfL client + tier-1/2 normalisation + fixtures (TM-4)`.
- **PR body:** `Closes TM-4`; lists deliverables, the retry policy, and
  the `tests/fixtures/tfl/` layout choice.

## What we're NOT doing

- No Kafka producers, no `aiokafka` usage — TM-B2.
- No Kafka consumers, no Postgres writes — TM-B3.
- No edits to `contracts/schemas/*` — tier-1 + tier-2 are frozen.
- No edits to `tests/test_contracts.py` or `tests/fixtures/*_sample.json`
  — out of track.
- No edits to `scripts/fetch_tfl_samples.py` — out of track; the
  existing script keeps working against the old fixture path.
- No new runtime dependency (`tenacity`, `stamina`, `respx`, etc.) —
  retry is hand-rolled; testing uses `httpx.MockTransport` which is
  built in.
- No `Settings(BaseSettings)` class — one env var (`TFL_APP_KEY`)
  does not justify it (CLAUDE.md rule 5).
- No logging wrapper — Logfire/`logging.basicConfig` is enough
  (CLAUDE.md rule 6). The client emits a `logfire.span` per request
  so throttling diagnostics land in the right tool.
- No end-to-end live-API test in CI — ingestion tests use fixtures
  only (AGENTS.md §3).

## Sub-phases

### Phase 3.1 — Fixtures (`tests/fixtures/tfl/`)

Populate the new fixture directory with real TfL responses (the member
regenerates locally via a small one-off script or by re-using
`scripts/fetch_tfl_samples.py` out-of-band, then commits the JSON).
Required files — one per endpoint method the client exposes:

- `tests/fixtures/tfl/line_status_tube.json` — `GET /Line/Mode/tube/Status`
- `tests/fixtures/tfl/line_status_multi_mode.json` —
  `GET /Line/Mode/tube,elizabeth-line,dlr,overground/Status`
- `tests/fixtures/tfl/arrivals_oxford_circus.json` —
  `GET /StopPoint/940GZZLUOXC/Arrivals`
- `tests/fixtures/tfl/disruptions_tube.json` —
  `GET /Line/Mode/tube/Disruption`

All files are real API responses (not hand-crafted). Each is a JSON
array matching the tier-1 Pydantic models. Commit them as-is; the
tier-1 schemas already tolerate extra fields via
`ConfigDict(extra="ignore")`.

### Phase 3.2 — Client module (`src/ingestion/tfl_client/`)

Files (all under the allowed path):

#### `src/ingestion/tfl_client/__init__.py`

Re-export the public surface:

```python
from src.ingestion.tfl_client.client import TflClient, TflClientError

__all__ = ["TflClient", "TflClientError"]
```

#### `src/ingestion/tfl_client/client.py`

- `class TflClient` — async context manager wrapping a single
  `httpx.AsyncClient`.
- Constructor signature:
  ```python
  def __init__(
      self,
      app_key: str,
      *,
      base_url: str = "https://api.tfl.gov.uk",
      timeout: float = 30.0,
      max_attempts: int = 3,
  ) -> None: ...
  ```
  - `app_key` required; constructor raises `TflClientError` if empty /
    `None` (fail-loud per CLAUDE.md §"Security-first — zero-trust").
- Class method `from_env(**kwargs) -> TflClient` that reads
  `TFL_APP_KEY` from the environment (`os.environ`; tests override via
  `monkeypatch.setenv`).
- `async def __aenter__(self) -> Self` instantiates
  `httpx.AsyncClient(base_url=base_url, timeout=timeout)` and keeps it
  on `self._http`.
- `async def __aexit__(self, *exc) -> None` closes the client.
- `async def _request(self, path: str, *, params: dict | None = None) -> Any` —
  central call site that:
  1. Builds the outbound parameters as a **new dict**:
     `outbound = {**(params or {}), "app_key": self._app_key}`.
     Never mutate the caller's `params` argument.
  2. Builds a redacted copy for tracing — `traced = {k: ("***" if k == "app_key" else v) for k, v in outbound.items()}` —
     and calls `self._http.get(path, params=outbound)` inside
     `logfire.span("tfl.request", path=path, params=traced)`. The
     `app_key` value is **never logged** (CLAUDE.md §"Security-first —
     Secrets").
  3. Implements the retry policy (see Phase 3.3).
  4. Calls `response.raise_for_status()` on non-retryable 4xx.
  5. Returns `response.json()`.
- Three public coroutines (tier-1 returns):
  ```python
  async def fetch_line_statuses(self, modes: Iterable[str]) -> list[TflLineResponse]: ...
  async def fetch_arrivals(self, stop_id: str) -> list[TflArrivalPrediction]: ...
  async def fetch_disruptions(self, modes: Iterable[str]) -> list[TflDisruption]: ...
  ```
  Each uses `TypeAdapter(list[Tfl...]).validate_python(...)` for
  efficient bulk parsing. Each validates input (`modes` non-empty;
  `stop_id` non-empty string).

#### `src/ingestion/tfl_client/retry.py`

Tiny hand-rolled retry helper (~30 lines) shared by `_request`:

- Signature:
  ```python
  async def with_retry(
      call: Callable[[], Awaitable[httpx.Response]],
      *,
      max_attempts: int,
  ) -> httpx.Response: ...
  ```
- Retry on: `httpx.TimeoutException`, `httpx.TransportError`, and
  responses with `status_code in {429, 500, 502, 503, 504}`.
- For 429 responses: honour `Retry-After` if present and parseable as
  a positive integer (seconds). If the header is absent, malformed, or
  uses the HTTP-date form, **fall back** to the standard exponential
  backoff below — never raise just because the header is unparseable
  (RFC 9110 allows date form; client must remain robust).
- Otherwise exponential backoff: `0.5 * 2 ** attempt` seconds, capped
  at 10s (`asyncio.sleep`).
- On final failure, raise `TflClientError` wrapping the last
  response / exception.

#### `src/ingestion/tfl_client/normalise.py`

Adapters mapping tier-1 → tier-2 payloads (pure functions, no
side-effects). Shape:

```python
def line_status_payloads(response: list[TflLineResponse]) -> list[LineStatusPayload]: ...
def arrival_payloads(response: list[TflArrivalPrediction]) -> list[ArrivalPayload]: ...
def disruption_payloads(response: list[TflDisruption]) -> list[DisruptionPayload]: ...
```

Details:

- `line_status_payloads` flattens the `lineStatuses[*].validityPeriods`
  into one payload per `(line_id, validity_period)`; `valid_from` /
  `valid_to` come from the validity period; `status_severity` + `reason`
  come from the parent `lineStatus`. Lines with no `validityPeriods`
  produce a single payload using `valid_from=now` and
  `valid_to=valid_from + 12h` (consistent with `test_contracts.py`
  convention); this default is documented in the function docstring.
- `arrival_payloads` maps field-by-field:
  `id → arrival_id`, `naptanId → station_id`, `lineId → line_id`,
  `platformName → platform_name`, `direction` passthrough,
  `destinationName → destination`, `expectedArrival → expected_arrival`,
  `timeToStation → time_to_station_seconds`, `vehicleId → vehicle_id`.
- `disruption_payloads` — TfL disruption responses are lossy (no stable
  `disruption_id` or `created` timestamp); the adapter synthesises
  `disruption_id` from a deterministic SHA-256 digest over a stable
  serialisation of the disruption — concretely
  `hashlib.sha256(json.dumps({"category": ..., "description": ..., "affected_routes": sorted(...)}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()` —
  taking the first 32 hex chars to keep IDs compact. Python's built-in
  `hash()` is rejected here because it is randomised per process and
  unstable across runs. `created` / `last_update` use
  `datetime.now(UTC)`. The docstring flags every synthesised field so
  TM-B2 knows it cannot trust them for deduplication without
  TfL-supplied keys.
- `summary` in the payload is a truncated `description` (160 chars)
  because the free TfL endpoint does not return a separate summary —
  documented in the docstring.

The adapters do **not** build `Event` envelopes (`LineStatusEvent`
etc.); wrapping payloads into events is a producer concern (TM-B2),
since the envelope needs `event_id`, `ingested_at`, source offsets.

### Phase 3.3 — Tests (`tests/ingestion/`)

Files:

- `tests/ingestion/__init__.py` — empty package marker.
- `tests/ingestion/conftest.py` — one fixture loading each JSON from
  `tests/fixtures/tfl/` into bytes; a factory helper building a
  `httpx.MockTransport` wired to a url→response mapping.
- `tests/ingestion/test_tfl_client.py`
  - `test_fetch_line_statuses_returns_tier1_models`
  - `test_fetch_arrivals_returns_tier1_models`
  - `test_fetch_disruptions_returns_tier1_models`
  - `test_app_key_in_query_params` — asserts every outbound request
    carries `app_key=<value>`.
  - `test_429_respects_retry_after` — first response 429 with
    `Retry-After: 1`, second 200; assert final response parsed.
  - `test_500_retries_then_succeeds` — 500 / 500 / 200 → succeeds.
  - `test_401_raised_immediately` — single 401 → `TflClientError`,
    one attempt only.
  - `test_timeout_retries_then_gives_up` — uses custom transport
    raising `httpx.TimeoutException` every time; asserts
    `TflClientError` after `max_attempts`.
  - `test_from_env_requires_app_key` — unset env var → `TflClientError`.
- `tests/ingestion/test_normalise.py`
  - `test_line_status_payloads_from_multi_mode_fixture`
  - `test_arrival_payloads_from_oxford_circus_fixture`
  - `test_disruption_payloads_from_tube_fixture`
  - Each test validates the resulting `*Payload` objects via the tier-2
    Pydantic models (roundtrip check on a representative item).

`pytest-asyncio`'s `asyncio_mode = "auto"` (already in
`pyproject.toml`) handles the `async def` tests transparently.

### Phase 3.4 — Verification gate

```bash
uv run task lint                                  # ruff + mypy strict on src/ingestion + contracts
uv run task test                                  # adds tests/ingestion/*
uv run bandit -r src --severity-level high        # HIGH severity only
make check                                        # includes dbt-parse + TS
```

All must exit 0 before PR. If `mypy strict` rejects `TypeAdapter`'s
type inference, use `TypeAdapter[list[TflLineResponse]](...)` with an
explicit generic parameter.

### Phase 3.5 — PR

Open PR from `feature/TM-B1-async-tfl-client` targeting `main`.

PR body (English):

- **Summary** — 4 bullets: async client; hand-rolled retry; tier-1→2
  normalisation; fixtures under `tests/fixtures/tfl/`.
- **Why hand-rolled retry** — quote AGENTS.md §"lean by default" rule
  about exotic retry policies; cite `httpx.MockTransport` as rationale
  for zero new deps.
- **Out of scope** — Kafka (TM-B2/TM-B3), live-API CI tests.
- **Test plan** — command list from Phase 3.4.
- **Closes TM-4**.

## Success criteria

- [ ] `src/ingestion/tfl_client/{client,retry,normalise,__init__}.py`
  implemented and importable.
- [ ] `tests/fixtures/tfl/` contains the four real JSON fixtures
  listed in Phase 3.1.
- [ ] `tests/ingestion/{test_tfl_client,test_normalise}.py` cover
  every behaviour listed in Phase 3.3; all green.
- [ ] `uv run task lint` passes (ruff + mypy strict).
- [ ] `uv run task test` passes (existing + new).
- [ ] `uv run bandit -r src --severity-level high` passes with no findings.
- [ ] `make check` passes end-to-end.
- [ ] PR opened with `Closes TM-4` in body.
- [ ] `PROGRESS.md` TM-B1 row updated to ✅ with the completion date.

## Open questions (resolved during planning)

1. **Fixture layout.** Add-alongside under `tests/fixtures/tfl/`.
   Existing `tests/fixtures/*_sample.json` stay untouched.
2. **Normalisation inclusion.** Include tier-1 → tier-2 normalisation
   in B1 (pure functions, no side effects).
3. **Retry implementation.** Hand-rolled `with_retry` helper under
   `src/ingestion/tfl_client/retry.py`.
4. **Logging / tracing.** One `logfire.span` per outbound request,
   tagged `path` and `params` (with `app_key` redacted). No custom
   metrics.
5. **App-key transport.** Query param (matches existing
   `scripts/fetch_tfl_samples.py`); header-based auth deferred until
   TfL deprecates the query form.
6. **Timeouts and connection pool.** Single `httpx.AsyncClient` per
   `TflClient` instance; caller owns lifecycle via `async with`. Tests
   exercise `aclose()` via the context manager exit.
