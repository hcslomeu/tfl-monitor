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
    "1 pyproject + flat compose": [0.85, 0.25]
    "Sub-packages with own toml": [0.20, 0.75]
    "Single AbstractVectorStore": [0.30, 0.65]
    "Plain pinecone client": [0.85, 0.30]
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
schemas separate the messy outside world from the clean internal wire format,
so producers, consumers, FastAPI, and the frontend can be built in parallel by
separate agents without colliding.

```mermaid
flowchart TB
    subgraph SOURCE[contracts/]
      OAPI[openapi.yaml<br/>OpenAPI 3.1]
      T1[schemas/tfl_api.py<br/>tier-1 raw shapes]
      T2[schemas/{line_status,arrivals,disruptions}.py<br/>tier-2 frozen events]
      DDL[sql/00*.sql<br/>raw + ref + analytics]
      DBTSRC[dbt_sources.yml]
    end

    OAPI -->|openapi-typescript| TS[web/lib/types.ts]
    OAPI -->|FastAPI route shapes| API[src/api]
    T1 -->|tfl_client normalises| ING[src/ingestion]
    T2 -->|wire format| KAFKA[(Kafka)]
    DDL -->|psql -f| PG[(Postgres)]
    DBTSRC -->|copied to| DBTSOURCES[dbt/sources/tfl.yml]
```

CI enforces the source-of-truth via `diff contracts/dbt_sources.yml
dbt/sources/tfl.yml` and a bidirectional OpenAPI ↔ Python drift test.

## Kafka earns its place

A cron-to-Postgres pipeline would technically deliver the same rows. Kafka is
worth its operational cost only because we exploit three properties:

1. **Decoupling** — producers keep polling while consumers redeploy.
2. **Replay** — rewinding `line-status` re-hydrates `stg_line_status` without a
   re-poll.
3. **Fan-out** — the same `arrivals` topic feeds `mart_bus_metrics_daily` and
   could feed a future live-dashboard pusher with no producer change.

If the WP only needed (1), we would skip Kafka. We exploit all three.

## dbt over raw SQL

```mermaid
graph LR
    raw[(raw.*<br/>JSONB landing)] --> stg[stg_*<br/>incremental merge<br/>defensive dedup]
    stg --> ints[int_* if needed]
    ints --> marts[mart_*<br/>composite-grain<br/>generic + singular tests]
    marts --> exposures[Exposures<br/>→ /reliability /disruptions /bus]
```

Raw SQL would also work — until a second person reads the codebase. dbt buys
us tests, lineage, and one-line documentation that ships with the code.

## Agent that does not hallucinate

Two design choices keep the agent honest:

1. **All five tools have typed Pydantic input/output.** The model cannot call
   `query_line_reliability` with a malformed `line_id` — Pydantic AI's Haiku
   normaliser canonicalises free text first.
2. **Retrieval cites chunks.** The RAG tool returns Pinecone chunks with their
   `doc_id` and `page` so any answer is traceable to a paragraph in a public
   document. LangSmith records the exact chunks that made it into the context.

If the answer hallucinates, the trace shows where — and the next iteration
prunes the bad retrieval, not "the LLM."

## Observability split

| Question | Tool |
|----------|------|
| How did the agent arrive at that answer? | LangSmith |
| Which chunks made it into the prompt? | LangSmith |
| How many tokens did this conversation cost? | LangSmith |
| Is the Kafka consumer keeping up? | Logfire |
| Why is `/reliability/{line_id}` p99 latency high? | Logfire |
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
| New ingestion topic, new mart, new agent tool | Three phases, fresh context per phase |
| Anything touching `contracts/` | Mandatory ADR + cross-track broadcast |

Track boundaries (A-infra / B-ingestion / C-dbt / D-api-agent / E-frontend /
F-polish) keep at most two agents on the codebase concurrently without
collisions.
