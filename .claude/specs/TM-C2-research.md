# TM-C2 — Research (Phase 1)

Read-only exploration. Captures the source-of-truth facts that constrain
TM-C2 (`stg_line_status` + `mart_tube_reliability_daily`) before any
plan or code is written. Every decision point ends with a short
**recommendation** that Phase 2 will lock down.

---

## 1. Status of the dbt project after TM-C1

- `dbt/dbt_project.yml` declares the `tfl_monitor` profile; staging /
  intermediate are `+materialized: view`, marts is `+materialized: table`.
- `dbt/profiles.yml` has two outputs: `dev` (local Postgres at
  `POSTGRES_HOST/PORT/USER/PASSWORD/DB`) and `ci` (defaults pointing at
  the GitHub Actions Postgres service). Both target schema `analytics`.
- `dbt/sources/tfl.yml` is a byte-identical mirror of
  `contracts/dbt_sources.yml` (CI `diff` gate enforces parity). It
  declares five source tables: `tfl.line_status`, `tfl.arrivals`,
  `tfl.disruptions` (schema `raw`), `tfl.lines`, `tfl.stations` (schema
  `ref`). All five include `not_null` (and `unique` on `event_id` /
  `line_id` / `station_id`).
- `dbt/models/{staging,intermediate,marts}/` are empty except for
  `.gitkeep` files (verified via `ls -a`).
- `dbt/tests/` does **not** exist yet (`dbt_project.yml` declares
  `test-paths: ["tests"]` so it will be picked up once we create it).
- `taskipy` exposes `dbt-parse = "dbt parse --project-dir dbt
  --profiles-dir dbt --target ci"`. There is no `dbt-build` /
  `dbt-test` task.
- CI (`.github/workflows/ci.yml`) runs `uv run task dbt-parse` in the
  `lint` job against a Postgres 16 service container. CI does **not**
  run `dbt build` or `dbt test` — that is intentionally local-only
  while there is no warehouse fixture (TM-A2 / TM-C3 will revisit).
- `make check` chains `lint → test → dbt-parse → web lint → web build`.

## 2. Shape of `raw.line_status`

DDL in `contracts/sql/001_raw_tables.sql`:

```sql
CREATE TABLE raw.line_status (
    event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    payload     JSONB NOT NULL
);
```

Indexes (`003_indexes.sql`): BTREE on `ingested_at DESC` + GIN on
`payload`. Both are useful for our staging filter (`ingested_at >
max(...)`) and for any payload-path lookups.

The producer (`src/ingestion/producers/line_status.py`) fills:

- `event_id`: `uuid.uuid4()` per snapshot.
- `event_type`: literal `"line-status.snapshot"`.
- `source`: literal `"tfl-unified-api"` (envelope default in
  `contracts.schemas.common.Event`).
- `ingested_at`: `datetime.now(UTC)` at envelope construction time
  (i.e. just after the TfL response, before the Kafka publish).
- `payload`: a `LineStatusPayload` model dumped to JSON.

The consumer (`src/ingestion/consumers/postgres.py`) writes via:

```sql
INSERT INTO raw.line_status (event_id, ingested_at, event_type, source, payload)
VALUES (...)
ON CONFLICT (event_id) DO NOTHING;
```

So `event_id` is unique by construction in `raw.line_status`.

## 3. Shape of the JSONB `payload`

`contracts/schemas/line_status.py` → `LineStatusPayload` (frozen, JSON-
serialised in the envelope):

| Field | Type | Notes |
|---|---|---|
| `line_id` | `str` | TfL identifier (e.g. `"victoria"`) — also the Kafka partition key |
| `line_name` | `str` | Human label (`"Victoria"`) |
| `mode` | `TransportMode` (enum string) | `"tube"`, `"elizabeth-line"`, `"overground"`, `"dlr"`, `"bus"`, `"national-rail"`, `"river-bus"`, `"cable-car"`, `"tram"` |
| `status_severity` | `int` 0..20 | Bounded by Pydantic; see `StatusSeverity` enum in `contracts/schemas/common.py` |
| `status_severity_description` | `str` | E.g. `"Good Service"`, `"Severe Delays"` |
| `reason` | `str \| None` | Free text, only when there is a disruption |
| `valid_from` | `datetime` (UTC) | Start of the status's validity window |
| `valid_to` | `datetime` (UTC) | End of the validity window; strictly > `valid_from` |

`StatusSeverity` enum codes worth modelling against:

- `0..6` ≈ disruption (special service / closed / suspended / delays)
- `9` = minor delays
- `10` = good service (the "happy path")
- `11..20` = closures / metadata flags

All fields are mandatory except `reason`. The Pydantic frozen model
guarantees the shape upstream — staging only needs to cast and
defensively dedup, not re-validate JSON paths.

## 4. KPI candidates for `mart_tube_reliability_daily`

The mart's grain (per the team-lead briefing) is
`line_id × calendar_date × status_severity`. Available signal once we
unnest `payload`:

1. **`snapshot_count`** — number of envelopes received for the
   (line, date, severity) triple. Trivially derived. Drives every
   ratio downstream.
2. **`first_observed_at` / `last_observed_at`** — `min`/`max` over
   `ingested_at`. Useful to bound when a severity actually appeared
   on a given day; lets the API answer "first severe-delay observed
   at HH:MM".
3. **`minutes_observed_estimate`** — `snapshot_count × producer_period
   / 60`. The producer cadence (`LINE_STATUS_POLL_PERIOD_SECONDS = 30`)
   is fixed, so each snapshot is ~30 s of wall-clock coverage. Document
   the assumption in `schema.yml`; the SQL hard-codes `30.0`.
4. **`status_severity_description`** — pick the first description seen
   for the triple. Severity codes are stable; descriptions are
   essentially a label, captured for human-readable downstream views.
5. **`mode` / `line_name`** — denormalised from the same envelope (one
   value per `line_id`, so `min()` is a safe pick; we still aggregate
   to keep the SQL pure-aggregation rather than dragging a self-join).

**Out of scope for TM-C2:** longest-disruption-window (requires
session-window logic over consecutive non-good snapshots — fragile
under uneven scrape cadence; defer to TM-C3 alongside the other marts
once we have more data shape evidence). The team-lead briefing
explicitly allows scoping KPIs to what raw fields provide.

A complementary daily summary KPI per `(line_id, calendar_date)` —
e.g. `pct_time_good_service` — naturally lives one grain above this
mart and is computed downstream by the API (TM-D2) or by a future
`mart_tube_reliability_daily_summary` (TM-C3). Keeping it out of the
TM-C2 model honours YAGNI and keeps the grain promise tight.

## 5. Observation timestamp

Two candidates for the calendar bucket:

- `ingested_at` — when our producer stamped the snapshot. Stable, set
  exactly once, monotonic across consumers.
- `payload.valid_from` / `valid_to` — TfL's claim of when the status
  applies. Often `valid_to` is hours / days in the future for planned
  closures, so it does **not** track when we sampled.

We sampled the line at `ingested_at`; the KPI we want is "what
proportion of *our observations* saw the line in good service".
Recommendation: use `date_trunc('day', ingested_at AT TIME ZONE 'UTC')`
as `calendar_date`. Document this in `schema.yml` so a future reader
does not confuse it with `valid_from`.

## 6. Materialization strategy

- **Staging** — incremental `merge` on `event_id`, filtered by
  `ingested_at > max(ingested_at)` in the existing target (with a
  `coalesce(..., '-infinity'::timestamptz)` for the cold start).
  Defensive `row_number()` dedup on `event_id` covers the (currently
  impossible) case of duplicate inserts upstream.
- **Mart** — `+materialized: table` (inherited from `dbt_project.yml`
  `marts:` config). Daily KPI volume is small; a full rebuild is
  cheap and avoids the incremental-key problem (the natural key is the
  triple, which is fine but a full table rebuild is simpler).
  Mart materialization stays at the project default — no per-model
  override needed.

## 7. Dedup vs PK

`raw.line_status.event_id` is the table's PRIMARY KEY (see DDL above)
and the consumer writes via `ON CONFLICT (event_id) DO NOTHING`. So
dedup at staging is *strictly* defensive. We still do it because:

1. The team-lead briefing explicitly calls for dedup keyed on
   `event_id`.
2. The staging model is the place a future ingestion path
   (e.g. backfill from S3, replay from another topic) could
   re-introduce duplicates.

## 8. Test surface

Built-in dbt tests cover most of what we need without `dbt_utils`:

| Layer | Column / Test | Purpose |
|---|---|---|
| stg | `not_null` on `event_id`, `line_id`, `status_severity`, `ingested_at` | matches the contract guarantees |
| stg | `unique` on `event_id` | matches `raw.line_status` PK |
| stg | `accepted_values` on `mode` | enum from `TransportMode` |
| stg | `accepted_values` on `status_severity` | 0..20 bounded by Pydantic + `StatusSeverity` |
| mart | `not_null` on `line_id`, `calendar_date`, `status_severity`, `snapshot_count` | grain integrity |
| mart | `not_null` on `mode`, `line_name` | denormalised from staging |
| mart | custom singular test `assert_mart_tube_reliability_daily_grain.sql` | composite uniqueness over `(line_id, calendar_date, status_severity)` — `dbt_utils.unique_combination_of_columns` would be cleaner, but adding `dbt_utils` violates YAGNI when one ~6-line SQL file does the job |
| custom | singular test `assert_status_severity_known.sql` | mirrors `accepted_values`; demonstrates a custom test without forcing every consumer to re-read the enum |

Compose: `dbt/tests/` is a new directory; `dbt_project.yml` already
points at `test-paths: ["tests"]` so it works out of the box.

## 9. Validation

- `uv run task dbt-parse` — already wired; should remain green when
  the new files land. CI gate.
- `uv run dbt build --project-dir dbt --profiles-dir dbt --target dev`
  — local manual command (requires `make up`); not added to CI or
  `make check` because there is no warehouse fixture in CI.
- `uv run task lint` — Ruff + format + mypy; SQL files are unaffected,
  but YAML / new test SQL files must not break the lint job. They
  won't — Ruff doesn't touch `.sql`/`.yml`.
- `uv run task test` — pytest. No new pytest is required; the
  custom dbt tests live in `dbt/tests/` and run via `dbt build`.
- `make check` — chains the above; needs to stay green.

## 10. Open questions for Phase 2

1. **Q1 — Mart materialization**: keep the project default (`table`) or
   override to `incremental`? *Recommendation*: keep `table`. KPI
   volume at this grain is tiny; the simplicity wins.
2. **Q2 — Producer cadence as a constant**: hard-code `30.0` in the
   mart SQL or read it from a dbt var? *Recommendation*: hard-code,
   with a Jinja comment pointing back at
   `LINE_STATUS_POLL_PERIOD_SECONDS`. dbt vars are an indirection that
   nobody else in this project uses (YAGNI).
3. **Q3 — Schema docs naming**: `schema.yml` (per the team-lead's
   briefing) vs `_stg__models.yml` (dbt convention). *Recommendation*:
   follow the briefing exactly — `dbt/models/staging/schema.yml` and
   `dbt/models/marts/schema.yml`.
4. **Q4 — Add `dbt_utils`?**: cleaner unique-combination test, plus
   `surrogate_key`. *Recommendation*: no — one custom SQL test is
   cheaper than a package + pin.
5. **Q5 — Mart granularity revisit**: the briefing says "by `line_id ×
   calendar_date × status_severity`" with examples (`% time in good /
   severe`, `longest disruption window`). Two of those examples
   (`% time in good`, `longest disruption window`) live one grain
   *above* the requested grain; we surface the building blocks
   (snapshot counts, first/last observed) and let the API or a
   downstream daily-summary mart compose them. *Recommendation*: ship
   the requested grain; document in `schema.yml` how to roll it up to
   "% time in good" in one query.
6. **Q6 — `dbt build` smoke**: do we attempt to run `dbt build`
   locally during the WP, or do we rely on `dbt parse` + manual review?
   *Recommendation*: attempt `dbt build` if a local Postgres is up
   (`make up`). If Compose isn't running, document the manual
   verification command in the PR body and skip the live run; CI
   `dbt-parse` is the merge gate.

---

Phase 2 plan locks each of these recommendations and writes the file
breakdown.
