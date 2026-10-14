# Engineering principles

The principles below are not aspirations — they are review gates. Every PR is
checked against them by the author and by Codex (acting as a reviewer agent).

## Lean by default

```mermaid
quadrantChart
    title Engineering trade-off space
    x-axis Hard to review --> Easy to review
    y-axis Few moving parts --> Many moving parts
    quadrant-1 "Sweet spot for this repo"
    quadrant-2 "Fragile but readable"
    quadrant-3 "Avoid"
    quadrant-4 "Over-engineered"
    "1 pyproject + flat src": [0.85, 0.25]
    "Sub-packages with own toml": [0.20, 0.75]
    "AbstractLLMProvider for one model": [0.30, 0.65]
    "Plain ChatAnthropic client": [0.85, 0.30]
    "Custom Typer CLI": [0.30, 0.55]
    "python -m module entry": [0.80, 0.25]
```

The repo is reviewed by a human + Codex. Anything that takes Codex more than
30 s to understand *why* it exists is over-engineered.

## Four hard rules

| Rule | Meaning | In practice |
|------|---------|-------------|
| **DRY** | Don't Repeat Yourself | Search for an existing helper before writing a new one |
| **KISS** | Keep It Simple, Stupid | Prefer the most direct working solution |
| **YAGNI** | You Aren't Gonna Need It | Build only what the WP asks for |
| **SoC** | Separation of Concerns | One module, one purpose |

The pattern that flags every violation: *"is there a second consumer right
now?"* If no — the abstraction can wait.

## Contracts-first parallelism

Every cross-service interface lives in `contracts/`. Two tiers of Pydantic
schemas separate the messy outside world from the clean internal shape, so the
TfL client, FastAPI, and the frontend can be built in parallel by separate
agents without colliding.

```mermaid
flowchart TB
    subgraph SOURCE[contracts/]
      OAPI[openapi.yaml<br/>OpenAPI 3.1]
      T1[schemas/tfl_api.py<br/>tier-1 raw shapes]
      T2[schemas/*.py<br/>tier-2 typed models]
    end

    OAPI -->|openapi-typescript| TS[web/lib/types.ts]
    OAPI -->|FastAPI route shapes| API[src/api]
    T1 -->|tfl_client normalises| ING[src/ingestion/tfl_client]
    T2 -->|FastAPI response| API
```

CI keeps the contract honest in both directions: every FastAPI route must
match an OpenAPI operation (and vice versa), and the TypeScript types
regenerated from the contract must equal the committed file.

## Live proxy over a warehouse

Hoarding TfL's feeds as warehouse history bought nothing but disk-full
incidents: the free-tier database was bricked three times before ADR 014
turned the app into a live proxy. The principle is YAGNI applied to data: TfL
already exposes the live API, so reading through on demand is simpler, cheaper,
and removes an entire failure class.

## Cut what has no reader

ADR 015 applied the same test to what was left. Once the RAG layer was no
longer wanted, Postgres held only a write-only chat log (already covered by
LangSmith traces) and a station table that already had a live TfL fallback.
Removing the database, dbt, pgvector, Bedrock, and the Lightsail box left a
stateless function with nothing to operate. A store can return under a future
ADR when a feature actually reads from it.

## Agent that does not hallucinate

Two design choices keep the agent honest:

1. **Every tool has typed Pydantic input.** The model cannot call a tool with
   malformed arguments, and free-text station names are resolved through TfL
   `/StopPoint/Search` before any journey or arrivals call.
2. **Every answer comes from a live tool call.** Status, disruptions, journeys,
   and arrivals are fetched from TfL at question time; journey and arrivals
   results render as structured cards straight from the tool output (ADR 011),
   so the model does not restate them in prose.

If an answer is wrong, the LangSmith trace shows which tool ran with which
arguments and what it returned.

## Observability split

| Question | Tool |
|----------|------|
| How did the agent arrive at that answer? | LangSmith |
| Which tool ran, with which arguments? | LangSmith |
| How many tokens did this conversation cost? | LangSmith |
| Why is `/disruptions/recent` p99 latency high? | Logfire |
| Is TfL throttling us with 429s? | Logfire |

Two hosted tools, zero self-hosted telemetry. ADR 004 has the full rationale.

## Security-first mindset

A short list of non-negotiables, enforced by Bandit + manual review:

- **Zero-trust** — never trust client data; revalidate on the backend.
- **Secrets** — `SecretStr` (Pydantic) and env vars; nothing in source.
- **Parameterised queries** — always; no f-string SQL.
- **CORS** — explicit allowlist; never `*` in production.
- **Security headers in Next.js** — `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`.
- **Bandit in CI** — blocks on HIGH severity.
- **Post-generation bug hunt** — after writing auth or data-handling code, ask
  *"how would a malicious user bypass this?"* before the PR opens.

## Three-phase WP delivery

For non-trivial WPs the agent runs three phases with `/clear` between them, so
each phase enters a fresh context window.

```mermaid
flowchart LR
    R[Phase 1<br/>Research<br/>read-only] --> CLR1[/clear/]
    CLR1 --> P[Phase 2<br/>Plan<br/>interactive,<br/>open questions resolved]
    P --> CLR2[/clear/]
    CLR2 --> I[Phase 3<br/>Implementation<br/>internal phases<br/>tests after each]
```

Every spec is a triple under `.claude/specs/`:

```text
TM-XXX-research.md
TM-XXX-plan.md
TM-XXX-spec.md   (older WPs only — newer ones merge into the plan)
```

Phase 3 stops if reality diverges from the plan and reports:

> "Expected: X. Found: Y. How should I proceed?"

This ships small, intentional PRs and avoids drift.

## Trivial vs non-trivial

| Type | Treatment |
|------|-----------|
| Typo, one-line fix, dependency bump | Direct PR, tests already cover it |
| New endpoint with one query | Plan inline, implement, ship |
| New live endpoint, new agent tool | Three phases, fresh context per phase |
| Anything touching `contracts/` | Mandatory ADR + cross-track broadcast |

Track boundaries (A-infra / B-ingestion / D-api-agent / E-frontend / F-polish)
keep at most two agents on the codebase concurrently without collisions.
