# TM-26 — Plan

**Issue:** `/api/v1/disruptions/recent` returns `affected_routes: []` (and
`affected_stops: []`) for every row. See `TM-26-research.md` for the full
layer map.

**Root cause:** TfL `/Line/Mode/{modes}/Disruption` (the current
producer source) never populates `affectedRoutes` / `affectedStops` on
the free tier. Every layer downstream forwards the empty arrays
faithfully. The fix is **isolated to the ingestion layer**: switch the
disruption source to `/Line/Mode/{modes}/Status?detail=true`, which
carries the populated nested disruption objects.

**Affected tracks:** B-ingestion (sole). No dbt, no API, no contract SQL,
no web change.

---

## Internal phases

### Phase A — Tier-1 contract (no change)

`TflLineStatusDisruption.affected_stops: list[dict[str, object]]` already
accepts the nested-form payload as-is. Each entry carries `naptanId`
directly (verified live), which is exactly what
`_extract_ids(items, "naptanId")` consumes. `affected_routes` is
discarded — the parent `Line.id` is the authoritative source. No tier-1
contract change needed.

### Phase B — TfL client: new fetcher

Files:

- `src/ingestion/tfl_client/client.py`
  - Add `fetch_line_disruptions(modes: Iterable[str]) -> list[TflLineResponse]`
    that hits `/Line/Mode/{modes_param}/Status?detail=true` and returns
    the same `TflLineResponse` adapter type. (Reuses the line-status
    response model — the only difference is the populated nested
    `disruption` objects.)
  - Keep `fetch_disruptions` for now to avoid touching unrelated tests;
    mark it with a one-line docstring note that it is deprecated and
    delete in Phase C.

Tests:

- `tests/ingestion/tfl_client/test_client.py` — happy-path call against
  the new endpoint, parametrised with both fixtures (the existing tube
  status fixture + the new `?detail=true` fixture from Phase D).

### Phase C — Normaliser rewrite

Files:

- `src/ingestion/tfl_client/normalise.py`
  - New `disruption_payloads_from_line_statuses(response: list[TflLineResponse])
    -> list[DisruptionPayload]` that:
    - Iterates `response` → `line.line_statuses` → `status.disruption`.
    - Skips `lineStatuses` with `disruption is None`.
    - Sets `affected_routes = [line.id]`.
    - Sets `affected_stops = _extract_ids(disruption.affected_stops, "naptanId")`
      (same helper the previous flow used; nested-form stop entries
      carry `naptanId` directly).
    - Sets `category`, `category_description`, `description`,
      `closure_text` from the nested disruption. `type` not present →
      drop from the synthetic ID inputs.
    - `summary = description[:160]` (unchanged).
    - `severity = 0` (unchanged — `Status?detail=true` does not surface
      severity on the nested disruption either).
    - `created` and `last_update` = now (UTC), as before.
    - `disruption_id` = SHA-256[:32] of `{category, closure_text,
      description (stripped), affected_routes (sorted)}`. `type` field
      removed.
  - Delete the old `disruption_payloads(response: list[TflDisruption])`
    function and its private helper `_extract_ids` (only used by the
    deleted function). Replace all imports.

Tests:

- `tests/ingestion/test_normalise.py` (or wherever `disruption_payloads`
  is covered):
  - Replace the existing disruption-normaliser test cases with cases
    over a `TflLineResponse` fixture that exercises:
    1. A `lineStatuses` entry with no `disruption` → produces zero
       payloads.
    2. A `lineStatuses` entry with a populated `disruption` →
       produces one payload with `affected_routes == [parent line.id]`,
       `affected_stops` matching the walk, `disruption_id` stable
       across invocations.
    3. Multiple `route_section_naptan_entry_sequence` entries
       contributing the same naptanId → `affected_stops` deduped.
    4. Multiple lines sharing the same `description` and `category` but
       different `Line.id` → distinct `disruption_id` (proves
       `affected_routes` is part of the hash).

### Phase D — Fixtures

Files:

- `tests/fixtures/tfl/line_status_tube_detailed.json` (new) — captured
  from `https://api.tfl.gov.uk/Line/Mode/tube/Status?detail=true`,
  trimmed to ≤3 lines × ≤3 lineStatuses to keep diff readable. Must
  include at least one `lineStatuses` entry with a populated
  `disruption`.
- `tests/fixtures/tfl/disruptions_tube.json` — keep until Phase C
  deletes its consumers, then delete.

The fixture is captured manually with `curl … | jq`; document the
capture command at the top of the file in a JSON-comment style key
(`"_source": "..."`).

### Phase E — Producer rewire

Files:

- `src/ingestion/producers/disruptions.py`
  - `DisruptionsProducer.run_once` calls `tfl_client.fetch_line_disruptions(...)`
    and `disruption_payloads_from_line_statuses(...)`.
  - Period and mode tuple unchanged.
- `src/ingestion/tfl_client/__init__.py` — re-export the new
  symbols, drop the removed ones.

Tests:

- `tests/ingestion/producers/test_disruptions_producer.py`:
  - Update the fake `TflClient` to expose `fetch_line_disruptions`
    returning the new fixture.
  - Update assertions on the published payloads: `affected_routes` is
    `[<line.id>]`, `affected_stops` is non-empty.

### Phase F — Cleanup

- Delete `fetch_disruptions` from `TflClient` and its tests.
- Delete `tests/fixtures/tfl/disruptions_tube.json`.
- Delete `TflDisruption` model (no remaining consumers).
- Re-run the verification gate (lint + test + bandit + make check).

### Phase G — Post-deploy manual verification

After the PR lands and the GHA `Deploy` workflow finishes (recall
napkin item 10 — assert via the public URL):

```
curl -fsS https://tfl-monitor-api.humbertolomeu.com/api/v1/disruptions/recent \
  | jq '.[0:3]'
```

Each item with a non-trivial description must carry a non-empty
`affected_routes` array. `affected_stops` may stay empty if the
upstream record has no `routeSectionNaptanEntrySequence` (e.g.
`Information` category disruptions sometimes do); not a failure mode.

---

## Success criteria

### Automated (must pass before push)

- `uv run task lint` — Ruff + mypy strict green.
- `uv run task test` — Pytest green, including the new normaliser and
  producer cases.
- `uv run bandit -r src --severity-level high` — no HIGH findings.
- `make check` — full chain (the napkin's pre-push gate).
- `uv run task dbt-parse` — confirms no dbt drift (no dbt change
  intended; this is a guard).

### Manual (after deploy)

- `curl -fsS https://tfl-monitor-api.humbertolomeu.com/api/v1/disruptions/recent | jq '[.[] | .affected_routes | length] | add'`
  returns a number > 0. (At least one disruption must report a
  non-empty `affected_routes` — verified on the live TfL feed at
  research time, eight RealTime disruptions on tube alone.)
- The frontend disruption banner / dashboard surfaces non-empty
  affected-routes pills again. (No web change needed — the API field
  is consumed verbatim by the existing `web/components/*Disruption*`
  surface.)

---

## What we're NOT doing

1. **Sharing one TfL call between line-status and disruptions
   producers.** Cleaner refactor but out of scope. Two independent
   calls remain; both within free-tier rate limits.
2. **Adding route-section granularity** (a new `affected_route_sections`
   column on `DisruptionPayload`). The contract docstring says
   "Line IDs impacted"; route sections belong in a future field.
3. **Historical raw-row backfill.** The synthetic ID changes (no
   `type`, populated `affected_routes`) will produce new IDs going
   forward. Old rows under previous IDs stay in `raw.disruptions` and
   `stg_disruptions` — harmless because the dbt mart fans out per
   disruption_id and the recent endpoint sorts by `last_update DESC`.
4. **Schema or dbt changes.** Verified empty (the data is already
   plumbed end-to-end as JSONB).
5. **Web / frontend changes.** The bug is server-side; the UI already
   renders the field when populated.
6. **Hardening synthetic ID against further upstream churn.** A SHA-256
   over `category + closure_text + description + sorted(affected_routes)`
   is already stable; further hardening is a separate WP.

---

## Open questions

None. Phase 1 research closes every decision the implementation
depends on (endpoint to switch to, semantics of `affected_routes` in
the new shape, hash composition without `type`).
