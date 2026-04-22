# AGENTS.md

Instructions for coding agents (Codex, and any other LLM with repository access) working in this project.

> This file mirrors `CLAUDE.md` and must be kept in sync. Any change to one must be reflected in the other. The rules below are the same; the audience is different.

---

## Codex's role in this repository

Codex acts as a **critical reviewer** of code produced by Claude Code, plus ad-hoc refactor assistant and conformance checker against the rules in this document.

Primary responsibilities:

1. **Verify conformance with the rules in this file** on every PR.
2. **Flag** violations: over-engineering, premature abstractions, unjustified dependencies, test coverage regressions.
3. **Suggest simplifications** when avoidable complexity is spotted.
4. **Validate contracts**: changes under `contracts/` must have an associated ADR; Codex rejects if missing.

---

## Language and communication

**Respond in Brazilian Portuguese (PT-BR)** in every direct interaction with the author (terminal chat, explanations, summaries, review findings delivered back in chat).

Keep in **English** — no PT-BR anywhere, ever: source code, docstrings, file/directory names, contracts, error messages, logs, tests, and **every artifact persisted to git or GitHub**:

- commit subjects + bodies
- PR titles + descriptions
- issue titles + bodies
- GitHub-posted PR reviews and review comments (anything written via `gh pr review`, `gh pr comment`, `gh issue comment`, or the GitHub UI)
- branch names, tag messages

Rule of thumb: if the text lives on disk in `.git/` or on `github.com`, it is English. If it lives only in the terminal conversation with the author, it is PT-BR. A review you write for the author's eyes in chat stays PT-BR; the same review, when it becomes a `gh pr review --body`, is translated to English before posting.

Rationale: English keeps git history portable (future maintainers, GitHub search, CI logs, linters); PT-BR in chat reduces the author's cognitive load without fragmenting the codebase or its history.

---

## Principle #1: lean by default

This project explicitly refuses over-engineering. When reviewing code, flag (and block if necessary) any of these:

- **Multiple `pyproject.toml`** beyond the root one
- **Oversized Makefiles** (>20 targets) or targets that wrap a single shell command that would already be simple
- **Single-implementation abstractions** (interface with one concrete class)
- **Unneeded design patterns** (Factory, Strategy, Repository) without ≥2 real use cases
- **Hierarchical Pydantic settings** for <15 variables
- **Custom structured logging** when Logfire already covers the need
- **Typer/Click CLIs** for simple scripts
- **Duplicate tooling** (Biome + ESLint, Ruff + Black)
- **Stacked decorators** without clear justification
- **Docker sidecars** in local dev (Grafana, Prometheus, etc. — we use hosted Logfire and LangSmith instead)
- **Caching layers** without evidence of need
- **Exotic retry policies** configured before a real error exists to handle

**Review rule of thumb:** if a snippet takes more than 30 seconds to understand *why*, it is probably over-engineered.

---

## Project overview

**tfl-monitor** is a standalone portfolio project with an end-to-end architecture: streaming TfL → Kafka (Redpanda) → Postgres → dbt → FastAPI → Next.js, plus a LangGraph agent that routes between SQL (warehouse) and RAG (TfL strategy documents via Pinecone + LlamaIndex + Docling).

It is independent from `ai-engineering-monorepo`. Any reused code is **copied and adapted**, not imported.

---

## Tech stack (locked)

| Layer | Choice | Rejection reason if altered |
|---|---|---|
| Python package manager | `uv` | Recent, fast, already decided |
| Python | 3.12 | All libs verified here |
| Warehouse | PostgreSQL 16 | Supabase-compatible |
| Broker | Redpanda | Kafka API, single binary |
| Orchestration | Airflow 2.10+ | Explicit portfolio skill |
| Transformations | dbt-core + dbt-postgres | — |
| API | FastAPI + sse-starlette | — |
| Agent | LangGraph 1.x | — |
| Structured extraction | Pydantic AI | For tool-level typed LLM calls only |
| RAG | LlamaIndex | — |
| Vector DB | Pinecone serverless | — |
| PDF | Docling | — |
| Embeddings | OpenAI text-embedding-3-small | — |
| LLMs | Claude Haiku (router) + Sonnet (answer) | — |
| Validation | Pydantic v2 | Used at every boundary |
| LLM observability | LangSmith | — |
| App observability | Logfire | Covers FastAPI/Postgres/HTTP/OTel |
| Frontend | Next.js 16 + shadcn/ui (Radix + Nova) + TS | Design from claude.design |
| Python linter | Ruff | Sole Python linter/formatter |
| Types | Mypy strict | — |
| TS linter | Biome | Sole TS linter/formatter |
| Tests | Pytest + Vitest | — |

**Changing any choice in this table requires a formal ADR in `.claude/adrs/`.**

---

## PR rules Codex must enforce

### 1. WP scope

- A PR must reference exactly one WP (`TM-XXX`)
- A PR must touch **only the WP's track directories**
- If a PR crosses tracks (e.g. touches `ingestion/` and `dbt/` at once), reject and ask for a split

### 2. Contracts

- Any change under `contracts/` requires:
  - An ADR in `.claude/adrs/NNN-title.md` linked in the PR
  - Regeneration of downstream artefacts (TS types, JSON schemas)
  - PR title prefixed with `contract:`

### 3. Tests

- New code without tests: reject
- Coverage must not drop
- Ingestion tests must use fixtures from `tests/fixtures/`, never live TfL API

### 4. Security (blockers)

- Hardcoded secrets: block
- `*` in production CORS: block
- `verify=False` on HTTP clients: block
- SQL built by string concatenation: block
- `print()` of env vars anywhere: block

### 5. Commits

- Subject in English, Conventional Commits style
- No `Co-Authored-By`
- Subject < 72 characters
- Reference to the WP or Linear issue when applicable
- **Heredoc commit messages** (`git commit -m "$(cat << 'EOF' ... EOF)"`) in the PR body or in any snippet shown to the author: **block**. The author's terminal does not handle heredocs reliably. Require the inline `-m "..."` format, chaining multiple `-m` flags if the message needs multiple paragraphs.

### 6. Dependencies

- New dependency added: PR must justify it in 1–2 lines in the body
- Abandoned dependencies (no release in >2 years): reject
- Versions pinned in lockfile, not floating

### 7. Observability

- New code paths in the agent or API should emit a Logfire span where useful (one per endpoint, one per tool call)
- LangGraph nodes inherit LangSmith tracing automatically — do not add custom LangSmith calls
- **Block** attempts to install Prometheus/Grafana/OpenTelemetry collector stacks — these are replaced by Logfire

---

## Contracts

`contracts/` is the single source of truth for interfaces:

- `contracts/schemas/*.py` — Pydantic v2 for Kafka events
- `contracts/openapi.yaml` — OpenAPI 3.1 for every endpoint
- `contracts/sql/*.sql` — Postgres DDL for raw tables
- `contracts/dbt_sources.yml` — dbt sources derived from the DDL

No other directory defines these interfaces. If a schema appears duplicated elsewhere, that is a bug.

---

## Review hygiene

When reviewing, Codex should respond with:

1. **Status**: `APPROVE` / `REQUEST_CHANGES` / `COMMENT`
2. **Summary** in 1–3 sentences (PT-BR)
3. **Blockers** (if any): clear bullets, each with file location
4. **Suggestions** (non-blocking): separated, clearly optional
5. **Conformance checklist**:
   - [ ] Scope respects track boundaries
   - [ ] Tests pass and cover new code
   - [ ] No over-engineering detected
   - [ ] No security violations
   - [ ] Commits follow convention
   - [ ] No changes under `contracts/` without ADR
   - [ ] No custom observability added (LangSmith + Logfire are the only allowed tools)

---

## Escalation

If Codex detects any of the following, escalate to the author before approving:

1. Introduction of a new runtime dependency not listed in the locked stack
2. Change to `docker-compose.yml` that adds a new service
3. Change to `pyproject.toml` that alters `python-version` or adds a new linter tool
4. Creation of a new top-level directory
5. Deletion of tests
6. Changes under `.github/workflows/`
7. Any attempt to substitute Logfire or LangSmith with an alternative

---

## Cross-references

- Claude Code instructions: [`CLAUDE.md`](./CLAUDE.md) — must stay in sync with this file
- ADRs: `.claude/adrs/`
- WP specs: `.claude/specs/`
- Current state: `PROGRESS.md`
