# TM-C1 — Implementation plan (Phase 2)

Source: `TM-C1-research.md` + author decision on `2026-04-23`.

## Summary

TM-000 already delivered every functional acceptance criterion declared
by TM-C1 in `SETUP.md` §7.3:

- `dbt_project.yml` + `profiles.yml` (dev + ci targets) configured.
- `dbt/sources/tfl.yml` byte-identical to `contracts/dbt_sources.yml`
  (CI `diff` gate in `.github/workflows/ci.yml`).
- `dbt-core` + `dbt-postgres` installed; `taskipy` `dbt-parse` task
  exists and is wired into `make check`.
- `uv run task dbt-parse` exits 0 (only a benign "unused paths"
  warning until TM-C2 adds models).

Per CLAUDE.md §"WP scope rules" rule 4 ("Every WP ships with tests")
and §"Anti-patterns — YAGNI", no additional surface is justified here.

**Decision (author-approved):** close TM-C1 as **already-delivered**.
Ship a minimal inline commit that:

1. Updates `PROGRESS.md` to flip the TM-C1 row to ✅ with a note
   pointing back to TM-000.
2. Verifies the `.gitkeep` files under `dbt/models/{staging,intermediate,marts}/`
   are already committed (they were added during the TM-000 scaffold —
   no new file needed here; the PR is **docs-only**).

No agent dispatch; the coordinator applies this directly.

## Execution mode

- **Author of change:** coordinator (inline in current session), not an
  agent-team member.
- **Branch:** `feature/TM-C1-close-as-delivered`.
- **PR title:** `chore(dbt): TM-C1 close as delivered by TM-000 (TM-5)`.
- **PR body:** references Linear TM-5 via `Closes TM-5`, quotes the
  research finding, lists touched files.
- **No ADR needed** (no contract edits, no locked-stack changes).

## What we're NOT doing

- Not adding a pytest parity test for `contracts/dbt_sources.yml` vs
  `dbt/sources/tfl.yml` — CI `diff` already enforces parity; duplicating
  it in pytest violates KISS.
- Not suppressing the dbt "unused configuration paths" warning — it
  disappears as soon as TM-C2 lands a single staging model.
- Not adding `dbt debug` to `make check` — requires a live Postgres,
  breaks offline `make check`.
- Not writing staging / intermediate / mart models — TM-C2 / TM-C3.
- Not reshaping `dbt/README.md` — leave the stub; TM-C2 will own docs.

## Sub-phases

### Phase 3.1 — `.gitkeep`s (already satisfied)

`dbt/models/{staging,intermediate,marts}/.gitkeep` are already tracked
in `main` (verified via `git ls-files dbt/models`). The TM-000 scaffold
added them. **No file creation needed**; this PR ships zero `dbt/`
changes. The verification was logged in the PR body so the audit trail
shows it was checked.

### Phase 3.2 — PROGRESS.md

Update the `TM-C1` row in `PROGRESS.md`:

```md
| 2 | TM-C1 | dbt scaffold | C-dbt | ✅ 2026-04-23 | Scope absorbed by TM-000 scaffold; `.gitkeep` pins for empty model dirs (already in main) |
```

Add to the "TM-000 notes" section (or a new "Scope absorption" block)
one line: "TM-C1's acceptance criteria were satisfied by TM-000; the WP
closes with a zero-code PR after verifying the CI diff + `dbt-parse`
pass."

### Phase 3.3 — Verification gate

Before opening the PR:

```bash
diff contracts/dbt_sources.yml dbt/sources/tfl.yml  # expect exit 0
uv run task dbt-parse                                # expect exit 0
uv run task lint                                     # expect exit 0
uv run task test                                     # expect exit 0
```

Skip `make check` locally if Docker is not running — the relevant
python/dbt checks above are sufficient to prove the WP's premise.

### Phase 3.4 — PR

Open PR from `feature/TM-C1-close-as-delivered` targeting `main`.

PR body structure (English, per CLAUDE.md §"Language and communication"):

- **Summary** — 2 lines pointing at TM-000 scope absorption.
- **Why close without implementation** — reference research file.
- **What this PR actually touches** — `PROGRESS.md` plus the Phase A
  spec files under `.claude/specs/TM-{B1,C1,D1}-{research,plan}.md`
  (the `.gitkeep` pins were already committed by TM-000; no `dbt/`
  files change here).
- **Acceptance criteria** — checklist copied from research, all
  already-green items marked `[x]`.
- **Closes TM-5**.

## Success criteria (copy of research, now checkable)

- [x] `dbt/models/{staging,intermediate,marts}/.gitkeep` are committed
  (verified `git ls-files dbt/models` on `2026-04-23`; pins came from
  TM-000).
- [x] `PROGRESS.md` TM-C1 row reads ✅ with the 2026-04-23 date and a
  one-liner citing TM-000 absorption.
- [ ] CI green on `main` after merge (all three jobs) — checked once
  the PR merges.
- [ ] Linear TM-5 transitions to Done on merge (automatic via the
  Linear↔GitHub integration) — checked once the PR merges.
