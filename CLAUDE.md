# CLAUDE.md

Guidance for Claude Code when working in this repository.

---

## Language and communication

**All direct chat responses to the author must be in Brazilian Portuguese (PT-BR).** This applies to:

- Explanations, summaries, and chat replies
- Questions asked back to the author during research/planning phases
- Review findings reported back to the author in terminal chat (before
  they are persisted anywhere)

The following must remain in **English** (no PT-BR anywhere, ever):

- Source code (identifiers, functions, classes, variables)
- Docstrings (Python ecosystem convention)
- File and directory names
- Content under `contracts/` (schemas, OpenAPI, SQL)
- Error messages and log output (English is lingua-franca for systems)
- Tests and assertions
- **Every artifact persisted to git or GitHub**: commit subjects **and
  bodies**; PR titles **and descriptions**; issue titles **and bodies**;
  GitHub-posted PR reviews and review comments (anything written via
  `gh pr review`, `gh pr comment`, `gh issue comment`, or the GitHub UI);
  branch names; tag messages.
- Markdown content of this file and `AGENTS.md`

**Rule of thumb:** if the text lives on disk in `.git/` or on
`github.com`, it is English. If it lives only in the terminal
conversation with the author, it is PT-BR. A review written for the
author's eyes in chat stays PT-BR; the same review, when it becomes a
`gh pr review --body`, is translated to English before posting.

Rationale: reduce cognitive load for the author during review, without fragmenting the codebase or making tools (Codex, context7, linters, CI logs) harder to work with.

---

## Principle #1: lean by default, no over-engineering

This repository is reviewed by the author and by Codex. Any structure too complex to review without external help **must be simplified**.

Hard rules:

1. **One `pyproject.toml` at the root.** Python modules are plain folders under `src/`, not sub-packages with their own `pyproject.toml`.
2. **A short `Makefile`** (max ~15 targets) for system orchestration (Docker, bootstrap, `check`). Pure-Python dev tasks use `uv run task <name>` via `[tool.taskipy.tasks]` in `pyproject.toml`.
3. **Minimal Docker Compose**: only services essential for local dev. No sidecars, no local observability (Grafana/Prometheus stay out — we use hosted observability instead).
4. **No "just-in-case" abstractions.** If there is one consumer of a function, don't create an interface. If there is one vector store (Pinecone), don't create an abstract factory. Abstract when the second case arrives.
5. **No elaborate hierarchical configuration.** One `.env` file. No nested Pydantic `BaseSettings` unless there are ≥15 variables.
6. **No custom structured logging wrapper.** Logfire handles structured logs; `logging.basicConfig` for anything it doesn't cover.
7. **No custom CLI** (Typer/Click) when a ~20-line script solves it.
8. **No Biome + ESLint, no Ruff + Black.** One tool per job.

When in doubt between "make it elegant" and "make it simple": **make it simple**. The reviewer prefers reading 40 direct lines over 200 "well-structured" ones.

---

## Before starting any task

Always read these files first:

```bash
cat PROGRESS.md
cat .claude/current-wp.md   # which WP is active
```

If a detailed spec exists at `.claude/specs/TM-XXX-spec.md` for the active WP, it is the source of truth — follow it strictly.

---

## Project overview

**tfl-monitor** is a standalone portfolio project demonstrating end-to-end data engineering + AI engineering: a streaming pipeline ingesting TfL (Transport for London) live feeds into a dbt-modelled PostgreSQL warehouse, with a RAG layer over TfL strategy documents and a conversational agent that routes between SQL and document retrieval.

**This is NOT part of the `ai-engineering-monorepo`.** It is a standalone repo. If you know patterns from the monorepo (`AsyncHTTPClient`, `VectorStore` abstraction, LangGraph agent state, etc.), **copy and adapt them** — do not import.

---

## Tech stack (locked — do not substitute without an ADR)

| Layer | Choice |
|---|---|
| Python package manager | `uv` |
| Python version | 3.12 |
| Warehouse | PostgreSQL 16 |
| Streaming broker | Redpanda (Kafka-compatible) |
| Batch orchestration | Apache Airflow 2.10+ (LocalExecutor) |
| Transformations | dbt-core + dbt-postgres |
| API | FastAPI + sse-starlette |
| Agent framework | LangGraph v1.x |
| Structured LLM extraction | Pydantic AI (for tool-level extraction; LangGraph remains the main agent) |
| RAG framework | LlamaIndex |
| Vector DB | Pinecone (serverless) |
| PDF ingestion | Docling |
| Embeddings | OpenAI `text-embedding-3-small` |
| LLMs | Anthropic Claude (Haiku for routing, Sonnet for final answer) |
| Data validation | Pydantic v2 (everywhere — Kafka events, API models, config) |
| LLM observability | LangSmith |
| App observability | Logfire (FastAPI, Postgres, OpenTelemetry) |
| Frontend | Next.js 16 + shadcn/ui (Radix + Nova preset) + TypeScript (design via claude.design) |
| Backend hosting | Railway |
| Frontend hosting | Vercel |
| Postgres (prod) | Supabase free tier |
| Kafka (prod) | Redpanda Cloud Serverless free tier |
| Python linter/formatter | Ruff (lint + format) |
| Type checker | Mypy strict |
| TS linter/formatter | Biome (chosen — do not add ESLint or Prettier) |
| Python tests | Pytest |
| TS tests | Vitest |

---

## Observability architecture

Two hosted tools, clearly separated by concern:

### LangSmith — LLM and agent tracing

- Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=...`, `LANGSMITH_PROJECT=tfl-monitor`
- LangGraph auto-instruments: every node, tool call, LLM invocation becomes a trace
- Pydantic AI also emits to LangSmith when the env vars are set
- Use it to debug: "why did the router pick the SQL tool?", "which retrieval chunks made it to the context?"

### Logfire — application and data tracing

- Initialise once in each service entrypoint:

```python
import logfire

logfire.configure(service_name="tfl-monitor-api")
logfire.instrument_fastapi(app)
logfire.instrument_psycopg()
logfire.instrument_httpx()
```

- Use structured logging via `logfire.info("message", **attributes)` rather than `print()` or bare `logging`
- Covers: request latency, SQL query plans, HTTP client calls, Kafka produce/consume timings
- Use it to debug: "which consumer is lagging?", "why is /reliability/{line_id} slow?"

**Division of labour:**

| Question | Tool |
|---|---|
| How did the agent arrive at that answer? | LangSmith |
| Which TfL endpoint is throttling us? | Logfire |
| How many tokens did this conversation cost? | LangSmith |
| Why is this endpoint p99 latency high? | Logfire |
| Did the retriever pull the right chunks? | LangSmith |
| Is the Kafka consumer keeping up? | Logfire |

Both free tiers are generous enough for this project. Do not implement custom metrics/tracing.

---

## Phase approach (for non-trivial WPs)

Follow three phases, using `/clear` between them:

### Phase 1 — Research (read-only)

- Explore the codebase to understand what exists
- Document findings in `.claude/specs/TM-XXX-research.md`
- Do not suggest improvements in this phase
- Run `/clear` when done

### Phase 2 — Plan (interactive)

- Read the research file from Phase 1
- Write a plan with internal phases and success criteria (automated + manual)
- Include a "What we're NOT doing" section
- Resolve ALL open questions before proceeding
- Get the author's confirmation before Phase 3
- Save to `.claude/specs/TM-XXX-plan.md`
- Run `/clear` when done

### Phase 3 — Implementation

- Read the plan from Phase 2
- Execute phase by phase
- Run tests after each phase — do not proceed if they fail
- If reality diverges from the plan, STOP and report:
  > "Expected: X. Found: Y. How should I proceed?"
- Avoid printing large files in chat; prefer showing small snippets

**For trivial tasks** (typo, one-line fix): go straight to implementation.

---

## Before committing

Always run:

```bash
uv run task lint      # ruff check + ruff format --check + mypy
uv run task test      # pytest
uv run task dbt-parse # if you touched dbt/

# TypeScript (if you touched web/)
pnpm --dir web lint
pnpm --dir web test
```

Or simply:

```bash
make check
```

---

## Git workflow

```bash
# Feature branch named by WP
git checkout -b feature/TM-XXX-short-description

# Commits in Conventional Commits style (subject in English)
git commit -m "feat(api): add /status/live endpoint"
git commit -m "fix(ingestion): handle TfL 429 rate limit"
git commit -m "chore(dbt): add not_null tests to stg_line_status"

# PR referencing the Linear issue
gh pr create --title "feat: TM-XXX description (LIN-Y)" --body "Closes LIN-Y"
```

### Commit rules

- **Provide git commands as text for the author to copy and run** rather than executing directly. This saves tokens and gives the author control.
- **No co-authorship**: do NOT add `Co-Authored-By` lines.
- **Conventional commits** in English on subject line.
- Subject line under 72 characters, imperative mood.
- Body may be in PT-BR if it helps the author review.

### Commit message formatting — HARD RULE

All `git commit` commands provided to the author **must use inline `-m "..."` format, never heredoc (`<< 'EOF'`) format**. The author's terminal does not handle heredoc blocks reliably.

- ✅ Correct — single-line message:
  ```bash
  git commit -m "feat(api): add /status/live endpoint"
  ```
- ✅ Correct — multi-line message using multiple `-m` flags (git concatenates them with blank lines):
  ```bash
  git commit -m "feat(api): add /status/live endpoint" -m "Implements the live line-status query against the warehouse. Closes LIN-12."
  ```
- ❌ Wrong — heredoc, breaks the author's terminal:
  ```bash
  git commit -m "$(cat << 'EOF'
  feat(api): add /status/live endpoint

  Long body here.
  EOF
  )"
  ```

If a commit message genuinely needs multiple paragraphs, chain multiple `-m` flags. One `-m` per paragraph.

---

## WP scope rules

1. **One WP, one PR.** Always.
2. **A WP touches only directories in its track.** If you find yourself editing `contracts/` during a non-TM-000 WP: stop and ask.
3. **Maximum 2 WPs running simultaneously.** If the orchestrator asks for more, flag it.
4. **Every WP ships with tests.** "I'll test it later" is not acceptable.

---

## Engineering principles

| Principle | Rule | In practice |
|---|---|---|
| **DRY** | Don't Repeat Yourself | Search for existing functions before creating new ones |
| **KISS** | Keep It Simple | Prefer the simplest solution that works |
| **YAGNI** | You Aren't Gonna Need It | Build only what is asked |
| **SoC** | Separation of Concerns | One module, one purpose |

---

## Security-first engineering

- **Zero-trust**: never trust client data. Revalidate on the backend.
- **Secrets**: never hardcode. Use `SecretStr` (Pydantic) and environment variables.
- **Parameterized queries**: always. No string interpolation in SQL.
- **CORS**: explicit allowlist. Never `*` in production.
- **Next.js security headers**: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`.
- **Bandit in CI**: block on HIGH severity findings.
- **Post-generation bug hunt**: after writing auth or data-handling code, ask yourself: *"How would a malicious user bypass this?"*

---

## Anti-patterns to avoid

- **Violating DRY**: check existing libraries before reinventing
- **Violating KISS**: don't add features, refactors, or "improvements" beyond what was asked
- **Violating YAGNI**: if it's not in the plan, don't build it
- **Violating SoC**: don't add unrelated code to a file
- **Security shortcuts**: don't disable CORS, skip input validation, or use `verify=False`
- **Over-observing**: do not add custom metrics/tracing — LangSmith + Logfire cover what we need

---

## Code generation standards

### Portfolio-ready code

All generated code must be production-quality. Follow:

#### DO

- Write concise, professional docstrings that explain **WHAT** the code does
- Use self-documenting variable and function names
- Include type hints on every parameter and return value
- Follow PEP 8 and Ruff rules
- Use inline comments only when logic is genuinely complex

#### DO NOT

- Pedagogical comments ("This is encapsulation...")
- Explain basic concepts in docstrings
- Comments that reveal AI-assisted generation
- Step-by-step explanations of standard patterns
- Over-comment obvious code

### Docstring format

Google-style, minimal:

```python
def create_issue(self, title: str, body: str) -> dict:
    """Create a new GitHub issue.

    Args:
        title: Issue title
        body: Issue body in Markdown

    Returns:
        Dictionary with 'number' and 'url' of created issue
    """
```

---

## Pydantic usage conventions

Pydantic is used **everywhere** data crosses a boundary:

- **Kafka events**: `contracts/schemas/*.py` — frozen Pydantic models, JSON-serialised on wire
- **FastAPI request/response**: route signatures use Pydantic models; FastAPI auto-generates OpenAPI
- **Config**: single `Settings(BaseSettings)` class at `src/<service>/config.py` reading from env
- **Tool arguments for agent**: every LangGraph tool has typed Pydantic input/output — the agent cannot call a tool with malformed args

### When to use Pydantic AI

Pydantic AI is a thin structured-output LLM client. It earns its place when:

- A tool needs to extract a typed struct from free text (e.g. `LineQuery(line_id, window_days)` from `"how's the Piccadilly line been lately?"`)
- A sub-task inside a LangGraph node needs a quick type-safe LLM call without the full graph machinery

Do **not** use Pydantic AI for:

- The main routing agent — LangGraph's stateful graph + tool calling handles this
- Anything that already has an Anthropic SDK equivalent with less ceremony
- Replacing Instructor patterns just for the sake of migration

---

## Context hygiene

- `/clear` between phases and between unrelated tasks
- When compacting, preserve: modified file paths, current WP number, test commands
- Discard exploration output and MCP lookup results during compaction

---

## MCP servers

| Server | When to use |
|---|---|
| **context7** | Up-to-date library docs (LangChain, FastAPI, pytest, Pydantic AI) |
| **Linear** | Create/update issues when completing WPs |
| **ide** | VS Code diagnostics |

**Prefer MCP lookups over pasting docs into chat.**

---

## WP completion checklist

When a WP is done:

1. [ ] All acceptance criteria from the spec met
2. [ ] `uv run task lint` passes
3. [ ] `uv run task test` passes
4. [ ] `uv run task dbt-parse` passes if `dbt/` or `contracts/sql/` was touched
4. [ ] `make check` passes end-to-end
5. [ ] `PROGRESS.md` updated with completion date and notes
6. [ ] Linear issue moved to `Done` (via Linear MCP)
7. [ ] PR opened, referencing the Linear issue
8. [ ] Git commands and PR description provided as text for the author to execute
