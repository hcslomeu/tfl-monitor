# TM-F1 — Research (Phase 1, read-only)

**WP:** TM-F1 — README polish + demo video + live URL
**Track:** F-polish
**Dependencies:** TM-E4 (✅), TM-A5 (✅), TM-F2 (✅)
**SETUP.md mandate (line 359):** "Finalise the README, shoot demo video, add live URL."

This file documents the current state of the artefacts TM-F1 has to touch.
No recommendations, no fixes — Phase 2 (plan) will resolve open questions
and choose direction.

---

## 1. Scope inputs

### 1.1 `SETUP.md` line 359 (the only formal acceptance line in the repo)

> TM-F1 | README polish plus demo video plus live URL | F-polish | TM-E4 | 7 | Finalise the README, shoot demo video, add live URL.

No detailed acceptance criteria exist beyond this one sentence. No
existing spec file (`.claude/specs/TM-F1-{spec,research,plan}.md` were
absent before this file).

### 1.2 Prior art on F-track polish

- `TM-F2` ships production wiring (frontend on real API). Spec lives at
  `.claude/specs/TM-F2-plan.md` — its "What we're NOT doing" section
  defers cosmetic items to future polish WPs. None of those deferred
  items map directly to TM-F1.

### 1.3 Live URLs already in production (as of 2026-05-20)

- API + agent: `https://tfl-monitor-api.humbertolomeu.com` (200 OK on
  `/health`, `/api/v1/status/live`, `/api/v1/disruptions/recent` per
  the prior session handover).
- Web: `https://tfl-monitor.humbertolomeu.com` and
  `https://tfl-monitor.vercel.app` (both target=production).
- Docs site: `https://hcslomeu.github.io/tfl-monitor/` (published by
  `.github/workflows/docs.yml`).

---

## 2. Current state of `README.md` (root)

Length: 301 lines. Structure (top-to-bottom):

1. Title + one-line tagline (lines 1–5).
2. Four badges: CI / docs / python / licence (lines 7–10).
3. Production callout — already names `tfl-monitor-api.humbertolomeu.com`
   and `tfl-monitor.humbertolomeu.com`, points at ADR 006 (lines 12–15).
4. Top-of-page link list with placeholders for live demo + demo video
   (lines 17–23).
5. "What this project is" (lines 27–42).
6. "Why this project exists" (lines 44–53).
7. ASCII architecture diagram (lines 57–74) + link to docs site.
8. Tech stack table (lines 79–99).
9. "Engineering highlights" — contracts-first, Kafka, dbt, agent,
   observability (lines 101–148).
10. Local development quickstart (lines 150–197).
11. RAG ingestion section (lines 199–217).
12. Production deployment cost table (lines 219–243).
13. Status table (lines 245–259).
14. Folder map (lines 261–281).
15. Data sources, licence, author (lines 283–301).

### 2.1 Stale lines confirmed via `grep`

| Line | Current content | Why it's stale |
|---|---|---|
| 22 | "🚀 **Live demo**: shipping with TM-A5 + TM-E4" | Both WPs done — live URLs already on lines 12–13. Placeholder text. |
| 23 | "🎬 **Demo video**: shipping with TM-F1" | Placeholder. TM-F1 is this WP — must replace with the actual link. |
| 86 | "Orchestration \| Apache Airflow 2.10+ \| LocalExecutor; portfolio-relevant skill" | ADR 006 + PROGRESS TM-A5 entry: Airflow removed from prod, host cron only. Tech-stack row over-claims. |
| 92 | "LLMs \| Claude Sonnet 3.5 + Haiku 3.5 \| Top-of-class tool calling" | ADR 006 + README lines 14–15: prod runs Claude 4.5 (Sonnet + Haiku) via Bedrock cross-region inference profiles. Version drift. |
| 259 | "✅ (TM-A5 done; TM-F1 demo video next)" inside the Phase 7 status row | Reflects pre-TM-F1 state. Must collapse to "✅" once demo video lands. |
| 270 | "│  └─ agent/         # Legacy graph (kept for parity until TM-A5 collapse)" | `src/agent/` still exists on disk (confirmed via `ls src/`). Either the legacy collapse never happened or the comment is outdated. Needs verification in Phase 2 before the README is edited. |

### 2.2 Non-stale but worth re-reading in Phase 2

- Tech-stack table (79–99): mentions `pydantic-ai`, `LangGraph 1.x`,
  `LlamaIndex + Pinecone + Docling`, Tailwind v4, Biome — all current
  per `pyproject.toml` and `web/package.json` (unverified — Phase 2
  must spot-check).
- Cost table (221–234): "$5.50/mo effective" matches the PROGRESS
  TM-A5 entry. Lightsail share derivation is documented.
- Local dev quickstart (156–166): still references Airflow via
  `make up`. Compose stack does run Airflow locally per CLAUDE.md, so
  this is consistent with the "Airflow stays in local dev" rule.
- RAG section (199–217): commands reference `uv run python -m rag.ingest`
  with the four flags documented in PROGRESS TM-D4 — still current.
- ADR 006 cross-link (243) resolves (`.claude/adrs/006-aws-deploy.md`
  exists).

---

## 3. Current state of `web/README.md`

Length: 115 lines. Structure: stack, layout, quickstart, surface table,
type regeneration, security headers, tests, status list.

### 3.1 Stale lines

| Line | Current content | Why it's stale |
|---|---|---|
| 111 | "TM-E2: disruption view (folded into TM-E5)." | Factually correct but mid-tense — PROGRESS shows TM-E5 done 2026-05-12. Reads as past tense fine; review whether to keep. |
| 114 | "TM-E4 (next): Vercel deploy, `NEXT_PUBLIC_API_URL` pointing at the prod API." | TM-E4 done 2026-05-13 and TM-F2 done 2026-05-16. "(next)" is wrong. |

### 3.2 Missing items

- No production URL stated inline (deep link to `tfl-monitor.vercel.app`
  or the apex). Root README has it; sub-README does not link forward.
- No demo video link.
- No screenshot of the dashboard. The repo currently ships no
  screenshots anywhere (`find . -name "*.png" -o -name "*.gif"` would
  confirm — deferred to Phase 2 unless decided otherwise).

### 3.3 Non-stale

- Stack list, layout tree, quickstart commands, surface-and-wiring
  table, type regeneration command, security headers, test count (68
  specs) match PROGRESS TM-E5 + TM-F2 records.

---

## 4. Demo video — current state

- No video asset committed to the repo.
- No mention of a hosting decision (GitHub-hosted MP4 via release asset,
  Loom, YouTube unlisted, asciinema for terminal-only flows).
- No shot list, no script, no recording tooling captured in `.claude/`.

The demo video deliverable is unscoped. Phase 2 must decide:

1. **Surface(s) to record** — dashboard one-pager? agent chat? both?
   The chat is the most differentiated surface (SSE token stream + tool
   call status) but requires a working prod agent (currently 503 if any
   of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `PINECONE_API_KEY` is
   missing — TM-D5 lifespan compiles to `None` otherwise; prod status
   unconfirmed in this research).
2. **Length** — portfolio convention is 60–120 s.
3. **Voiceover vs captions vs silent walkthrough.**
4. **Hosting + embed strategy** — Markdown supports neither
   auto-playing video nor `<video>` reliably across GitHub UI. Common
   choices: animated GIF (heavy, low fidelity), Loom/YouTube link,
   release-asset MP4 with poster image.

---

## 5. Live URL — current state

Two live URLs already published in the README production callout
(lines 12–13). What TM-F1 still has to do for "add live URL":

- Replace the placeholder line 22 ("shipping with TM-A5 + TM-E4") with
  an actual top-of-page link to the live demo. Decision needed: which
  URL fronts the placeholder — apex (`tfl-monitor.humbertolomeu.com`)
  or Vercel default (`tfl-monitor.vercel.app`).
- Smoke the URL before linking (Phase 3) — already 200 OK in the prior
  session handover; recheck because state may have drifted.

---

## 6. Related files that may need a one-line update

Lower-priority drift discovered while researching the READMEs:

- `src/README.md` — exists; not read in Phase 1. If it documents `agent/`
  as legacy/collapsed, must reconcile with line 270 of the root README.
- `.claude/current-wp.md` — must be flipped to TM-F1 active before
  Phase 2 work begins.
- `PROGRESS.md` — TM-F1 row currently `⬜`. Updated only on completion
  per the WP completion checklist (CLAUDE.md).
- `docs/` (MkDocs site) — `README.md` declares the docs site is the
  expanded README. Drift on Airflow / Claude 4.5 / live URL likely
  mirrored there. Out-of-scope flag: Phase 2 decides whether TM-F1
  touches docs or defers to a follow-up WP.

---

## 7. Repo facts cross-checked

- `.github/workflows/ci.yml` exists → CI badge URL on line 7 is valid.
- `.github/workflows/docs.yml` exists → docs badge + Pages publish path
  are valid.
- `.github/workflows/deploy.yml` exists → matches the GHA SSH deploy
  described in PROGRESS TM-A5.
- `.github/workflows/claude.yml` + `claude-code-review.yml` exist (the
  automatic Claude Opus PR review workflow added in `fa3fc74`).
- `.claude/adrs/006-aws-deploy.md` exists → README cross-link resolves.
- `infra/README.md` exists → operator quickstart link on line 241
  resolves.
- `src/agent/` directory exists on disk → README line 270 is
  consistent with current state, but the comment "kept for parity until
  TM-A5 collapse" needs Phase 2 to decide whether the collapse was
  silently dropped or is still pending.

---

## 8. Open questions for Phase 2

1. **Demo video hosting**: release-asset MP4 + poster, Loom link,
   YouTube unlisted, or animated GIF? Author preference unknown.
2. **Demo video shot list**: which surfaces, in what order, with or
   without voiceover, target length.
3. **Legacy `src/agent/` collapse**: was it abandoned, deferred, or
   silently shipped? Affects whether README line 270 is rewritten as
   "still legacy", deleted, or the directory itself is removed (that
   would no longer be a TM-F1 read-only-polish task and probably
   warrants a separate WP).
4. **Tech-stack version-drift fix scope**: just the two confirmed lines
   (86 Airflow, 92 Claude 3.5) or a fuller audit?
5. **Top-of-page placeholder copy**: replace line 22's "Live demo:
   shipping with TM-A5 + TM-E4" with the apex URL, the Vercel URL, or
   both side-by-side?
6. **`web/README.md` scope**: just lines 111 + 114, or full re-polish?
7. **Docs site (`docs/`, MkDocs)**: in scope for TM-F1 or follow-up WP?
8. **Demo-video recording tooling**: macOS QuickTime + iMovie, ffmpeg
   capture, Cleanshot, OBS? Constrained by what the author has
   installed (unknown).

---

## 9. What this research did NOT do

- Did not edit any file.
- Did not run the production smoke (the prior session handover already
  confirmed 200 OK; Phase 3 reconfirms before publishing).
- Did not read `src/README.md`, `docs/`, `infra/README.md`,
  `ARCHITECTURE.md`, or any `.claude/adrs/*.md` beyond confirming ADR
  006's existence and date.
- Did not inventory the `pyproject.toml` / `web/package.json` versions
  to validate every row of the tech-stack table. Phase 2 must scope
  the audit if a full version pass is wanted.
- Did not make any recommendations on which polish items belong in
  TM-F1 vs a follow-up WP.

---

## 10. Phase 2 entry checklist

Phase 2 must:

- Read this file end to end.
- Resolve every open question in §8 with the author (chat in PT-BR).
- Write `.claude/specs/TM-F1-plan.md` with internal phases + automated
  and manual success criteria + a "What we're NOT doing" section.
- Get explicit author confirmation before Phase 3.
