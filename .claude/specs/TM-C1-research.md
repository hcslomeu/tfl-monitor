# TM-C1 — Research (Phase 1)

Read-only exploration. Track: **C-dbt**. Linear issue: **TM-5** (open).

Objective from `SETUP.md` §7.3: "Initialise the dbt project with sources pointing at raw tables."

## Scope boundary

Allowed paths: `dbt/`.
Forbidden without ADR: `contracts/` (AGENTS.md §2).

## What already exists (delivered by TM-000 + TM-A1)

### dbt project skeleton

- `dbt/dbt_project.yml` — profile `tfl_monitor`, paths declared
  (`models`, `seeds`, `tests`, `analyses`, `macros`, `snapshots`),
  materialisations set (`staging` → view, `intermediate` → view,
  `marts` → table). Target path `target`.
- `dbt/profiles.yml` — two outputs (`dev`, `ci`) against Postgres, both
  read from `POSTGRES_*` env vars with safe fallbacks. Target defaults
  to `dev`.
- `dbt/sources/tfl.yml` — mirrors `contracts/dbt_sources.yml` byte-for-byte
  (verified via `diff` — exit 0). Declares source `tfl` over schemas
  `raw` (three streaming tables: `line_status`, `arrivals`, `disruptions`)
  and `ref` (two static tables: `lines`, `stations`). Column-level
  `not_null` / `unique` tests already wired.
- `dbt/models/{staging,intermediate,marts}/` — empty directories.
- `dbt/README.md` — 3-line stub referring to TM-C2/TM-C3 for real models.

### Source-of-truth enforcement

- Root `Makefile`:
  - `sync-dbt-sources` target: `cp contracts/dbt_sources.yml dbt/sources/tfl.yml` (one-way sync helper).
  - `check` target invokes `uv run task dbt-parse`.
- `pyproject.toml`:
  - Dev deps include `dbt-core>=1.9` and `dbt-postgres>=1.9`.
  - `[tool.taskipy.tasks]` defines
    `dbt-parse = "dbt parse --project-dir dbt --profiles-dir dbt --target ci"`.
- `.github/workflows/ci.yml` (lint job):
  - Step: `diff contracts/dbt_sources.yml dbt/sources/tfl.yml` — blocks PR
    if the mirror drifts.
  - Step: `uv run task dbt-parse` with Postgres service container;
    env points to the ephemeral CI Postgres.

### Raw DDL that sources depend on

- `contracts/sql/001_raw_tables.sql` — `raw.{line_status,arrivals,disruptions}`
  with `pgcrypto`, `event_id UUID PK DEFAULT gen_random_uuid()`,
  `ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()`, plus `event_type`,
  `source`, `payload JSONB`. Matches what `dbt/sources/tfl.yml` asserts.
- `contracts/sql/002_reference_tables.sql` — reference schema for `lines` / `stations` (assumed from yml; not re-read here).

### Acceptance criteria from SETUP.md §7.3

> "Initialise the dbt project with sources pointing at raw tables."

All functionally satisfied.

## Current state verification

Local `uv run task dbt-parse` against `ci` target:

```text
19:04:33  Running with dbt=1.11.8
19:04:33  Registered adapter: postgres=1.10.0
19:04:33  [WARNING]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
There are 3 unused configuration paths:
- models.tfl_monitor.staging
- models.tfl_monitor.intermediate
- models.tfl_monitor.marts
19:04:33  Performance info: dbt/target/perf_info.json
```

Exit 0. Warnings are expected — staging/intermediate/marts
materialisation defaults have nothing to bind to because models land in
TM-C2 / TM-C3.

## Gap analysis — what, if anything, is left for TM-C1

This is the core finding. Against the stated acceptance criteria, TM-C1
is already delivered. Possible residual polish items, all optional:

| # | Item | Value | Risk / cost |
|---|---|---|---|
| G1 | Add `.gitkeep` under `dbt/models/{staging,intermediate,marts}/` | Keeps empty dirs committed so TM-C2 doesn't start by re-creating them | ~3 lines in 3 files; zero functional impact |
| G2 | Add Pytest-level source YAML parity test (duplicates CI `diff`) | Catches drift locally before pushing | Redundant with the CI step; would live under `tests/dbt/`; marginal value |
| G3 | Expand `dbt/README.md` with env-var table + how-to-run | Ergonomics for reviewers / interviewers | Docs only; YAGNI risk if TM-C2/C3 overhauls it |
| G4 | Suppress the "unused configuration paths" warning by moving the default materialisations into a `staging/_staging.yml` (or removing them until TM-C2) | Cleaner dbt parse output | Risks bike-shed; no functional impact |
| G5 | Add a `dbt debug` step to CI or `make check` | Verifies DB connectivity end-to-end | Requires a running Postgres in `make check`, breaks offline runs; TM-A3 territory |
| G6 | Tests directory `dbt/tests/` with a trivial schema test template | Optional; TM-C2/C3 will populate | Empty scaffolding → YAGNI |

None of G1–G6 are required by the spec.

## Key documents reviewed

- `CLAUDE.md` — one WP = one PR = one track; `dbt/` only.
- `AGENTS.md` — Codex blocks over-engineering.
- `SETUP.md` §7.3, §10.1, §10.3.
- `PROGRESS.md` — TM-C1 row marked ⬜.
- `.claude/specs/TM-A1-plan.md` — structure template to mirror.
- `contracts/dbt_sources.yml`, `dbt/sources/tfl.yml`, `dbt/dbt_project.yml`, `dbt/profiles.yml`, `dbt/README.md`, `Makefile`, `pyproject.toml`, `.github/workflows/ci.yml`, `contracts/sql/001_raw_tables.sql`.

## Open questions for the planning phase

1. **Headline question.** Given all acceptance criteria are already met,
   should TM-C1 be:
   - (a) **Closed as already-delivered** via a tiny polish-only PR
     (update `PROGRESS.md`, close Linear TM-5, optionally land G1 and G3).
   - (b) **Executed with deliberate scope-padding** (G1 + G2 + G3 + G4)
     to create a visible PR. Portfolio-optics only.
   - (c) **Merged into TM-C2** scope and Linear TM-5 closed as "absorbed".
2. If we run an agent on TM-C1 with no code changes left, the agent's PR
   risks triggering the AGENTS.md §1 "over-engineering" guard rail.
3. Path forward must be decided before locking `TM-C1-plan.md`; research
   is intentionally prescription-free per CLAUDE.md Phase 1 rules.
