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

1. Pins empty dbt model directories with `.gitkeep` so TM-C2 does not
   start by re-creating them.
2. Updates `PROGRESS.md` to flip the TM-C1 row to ✅ with a note
   pointing back to TM-000.

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

### Phase 3.1 — `.gitkeep`s

Create three empty files to anchor the model directories in git:

- `dbt/models/staging/.gitkeep`
- `dbt/models/intermediate/.gitkeep`
- `dbt/models/marts/.gitkeep`

Directories already exist on disk and are committed because the
`TM-000` scaffold added `*/.gitkeep` implicitly — verify via
`git ls-files dbt/models`. If `.gitkeep` entries are already present,
skip this phase and note it in the PR body.

### Phase 3.2 — PROGRESS.md

Update the `TM-C1` row in `PROGRESS.md`:

```
| 2 | TM-C1 | dbt scaffold | C-dbt | ✅ 2026-04-23 | Scope absorbed by TM-000 scaffold; `.gitkeep` pins for empty model dirs (see PR) |
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
- **What this PR actually touches** — 3 `.gitkeep`s + PROGRESS.md.
- **Acceptance criteria** — checklist copied from research, all
  already-green items marked `[x]`.
- **Closes TM-5**.

## Success criteria (copy of research, now checkable)

- [ ] `dbt/models/{staging,intermediate,marts}/.gitkeep` are committed.
- [ ] `PROGRESS.md` TM-C1 row reads ✅ with the 2026-04-23 date and a
  one-liner citing TM-000 absorption.
- [ ] CI green on `main` after merge (all three jobs).
- [ ] Linear TM-5 transitions to Done on merge (automatic via the
  Linear↔GitHub integration).
