# Tech stack

Every choice is locked unless an ADR overrides it. The rejection column says
*why* the choice was made, so reviewers can see the trade-off without digging.

## Locked stack

| Layer | Choice | Why this, not the alternative |
|-------|--------|-------------------------------|
| Python package manager | [`uv`](https://docs.astral.sh/uv/) | Fast, single static binary, lockfile-first |
| Python | 3.12 | Match production base images; PEP 695 generics |
| Streaming broker | None | Live TfL proxy — no broker (ADR 014) |
| Database | PostgreSQL 16 | App-essentials + pgvector; no feed warehouse (ADR 014) |
| Transformations | [dbt-core](https://www.getdbt.com/) + dbt-postgres | Seeds + `dim_stations` only — tests, docs, lineage |
| Orchestration | Host cron | One-shot dbt seed + `dim_stations` build on deploy (ADR 008/014) |
| Ingestion | `httpx` + Pydantic v2 | Async retry; read-through to the TfL live API (ADR 014) |
| API | [FastAPI](https://fastapi.tiangolo.com/) + `sse-starlette` | Async, typed, OpenAPI 3.1 auto-emitted |
| Agent framework | [LangGraph](https://langchain-ai.github.io/langgraph/) 1.x | Stateful graph, native tool calling, LangSmith integration |
| Structured extraction | [Pydantic AI](https://ai.pydantic.dev/) | Tool-level typed LLM calls (e.g. `LineId` normaliser) |
| RAG | [LlamaIndex](https://www.llamaindex.ai/) | `PGVectorStore`, `doc_id` metadata filter per doc |
| Vector DB | pgvector (Supabase Postgres) | `tfl_strategy_docs` table (1024 dim, cosine) |
| PDF | [PyMuPDF](https://pymupdf.readthedocs.io/) | Text extraction + LlamaIndex `SentenceSplitter` (ADR 013) |
| Embeddings | AWS Bedrock Titan v2 `amazon.titan-embed-text-v2:0` | 1024-dim; billed within Bedrock usage |
| LLMs | Claude Sonnet (answers) + Haiku (router/extractor) | Sonnet 4.5 + Haiku 4.5 via Bedrock (Anthropic 3.5 fallback) — top-of-class tool calling |
| Validation | Pydantic v2 | Used at *every* boundary: FastAPI, config, tools |
| LLM observability | [LangSmith](https://www.langchain.com/langsmith) | Auto-instruments LangGraph nodes / tools / LLM calls |
| App observability | [Logfire](https://logfire.pydantic.dev/) | OpenTelemetry-native: FastAPI / Postgres / HTTP |
| Frontend | Next.js 16 + shadcn/ui (Radix + Nova) | Server components, Tailwind v4, claude.design preset |
| Python lint/format | [Ruff](https://docs.astral.sh/ruff/) | Sole linter and formatter — no Black, no isort |
| Type checker | [Mypy](https://mypy.readthedocs.io/) strict | Across `src/` and `contracts/` |
| TS lint/format | [Biome](https://biomejs.dev/) | Sole TS tool — no ESLint, no Prettier |
| Python tests | Pytest + `pytest-asyncio` | Markers separate `unit`, `integration`, `airflow` |
| TS tests | Vitest + RTL | Same import paths as Next, `jsdom` env |

## Hosting (production)

| Concern | Host | Tier |
|---------|------|------|
| Backend compute | AWS EC2 t4g.small spot, single instance | ~$4/mo |
| LLM | AWS Bedrock (`us-east-1`) | ~$2-3/mo at portfolio traffic |
| Postgres | Supabase free | $0 |
| Vector DB | pgvector (in Supabase Postgres) | $0 |
| Frontend | Vercel hobby free | $0 |
| Image registry | GHCR (public repo) | $0 |
| HTTPS | DuckDNS + Caddy auto-LE | $0 |
| Observability | Logfire + LangSmith free tiers | $0 |

Steady-state target: **~$6/mo**. Full breakdown lives in
[Deployment](deployment.md).

## What we explicitly avoid

These are not oversights — they are deliberate, motivated by the *lean by
default* principle in [`CLAUDE.md`](https://github.com/hcslomeu/tfl-monitor/blob/main/CLAUDE.md).

!!! danger "Anti-patterns"
    - **Multiple `pyproject.toml`s.** One root, one source of truth.
    - **Sidecar observability stacks.** No Prometheus / Grafana / OTel collector — Logfire and LangSmith cover what we need.
    - **Single-implementation abstractions.** No `VectorStoreFactory` for one pgvector store, no `LLMProvider` for one Claude.
    - **Custom CLIs (Typer, Click)** when a 20-line `python -m` script does the job.
    - **Duplicate tooling.** No Biome + ESLint, no Ruff + Black.
    - **Custom structured logging.** Logfire wraps `logging`; `logfire.info(...)` for everything it does not auto-instrument.

When in doubt between *elegant* and *simple*: simple wins. The reviewer would
rather read 40 direct lines than 200 well-structured ones.

## Tooling commands

The two entry-points an outside reader needs:

=== "Python"

    ```bash
    uv sync                     # install deps from lockfile
    uv run task lint            # ruff + mypy strict
    uv run task test            # pytest (no integration, no airflow)
    uv run task dbt-parse       # dbt project compiles
    ```

=== "TypeScript"

    ```bash
    pnpm --dir web install
    pnpm --dir web lint         # Biome
    pnpm --dir web test         # Vitest + RTL
    pnpm --dir web build        # Next production build
    ```

=== "Everything"

    ```bash
    make check     # chains all of the above
    make up        # boots Postgres locally
    make seed      # loads fixtures into local Postgres
    ```
