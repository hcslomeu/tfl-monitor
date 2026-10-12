# Tech stack

Every choice is locked unless an ADR overrides it. The rejection column says
*why* the choice was made, so reviewers can see the trade-off without digging.

## Locked stack

| Layer | Choice | Why this, not the alternative |
|-------|--------|-------------------------------|
| Python package manager | [`uv`](https://docs.astral.sh/uv/) | Fast, single static binary, lockfile-first |
| Python | 3.12 | PEP 695 generics; supported by the Vercel Python runtime |
| Database | None | Stateless API; nothing to persist (ADR 015) |
| Streaming broker | None | Live TfL proxy, no broker (ADR 014) |
| Ingestion | `httpx` + Pydantic v2 | Async retry; read-through to the TfL live API (ADR 014) |
| API | [FastAPI](https://fastapi.tiangolo.com/) + `sse-starlette` | Async, typed, OpenAPI 3.1 auto-emitted |
| Agent framework | [LangGraph](https://langchain-ai.github.io/langgraph/) 1.x | `create_react_agent`, native tool calling, LangSmith integration |
| LLM | Anthropic API direct via `langchain-anthropic` | Model from `CHAT_MODEL` (default `claude-haiku-5-5`), effort low, 4096-token cap, prompt caching |
| Validation | Pydantic v2 | Used at *every* boundary: FastAPI, TfL payloads, tool arguments |
| LLM observability | [LangSmith](https://www.langchain.com/langsmith) | Auto-instruments LangGraph nodes / tools / LLM calls |
| App observability | [Logfire](https://logfire.pydantic.dev/) | OpenTelemetry-native: FastAPI requests + TfL call spans |
| Frontend | Next.js 16 + shadcn/ui (Radix + Nova) | Server components, Tailwind v4, claude.design preset |
| Backend hosting | Vercel (Fluid compute, `lhr1`) | Git-driven deploys, CDN in front of the function (ADR 015) |
| Frontend hosting | Vercel | Same platform as the API |
| Python lint/format | [Ruff](https://docs.astral.sh/ruff/) | Sole linter and formatter: no Black, no isort |
| Type checker | [Mypy](https://mypy.readthedocs.io/) strict | Across `src/` and `contracts/` |
| TS lint/format | [Biome](https://biomejs.dev/) | Sole TS tool: no ESLint, no Prettier |
| Python tests | Pytest + `pytest-asyncio` | `integration` marker opts into live TfL / Anthropic calls |
| TS tests | Vitest + RTL | Same import paths as Next, `jsdom` env |

## Hosting (production)

| Concern | Host | Cost guard |
|---------|------|------------|
| API | Vercel project `tfl-monitor-api` (Pro, Fluid compute) | Vercel Spend Management |
| Frontend | Vercel project `tfl-monitor` | Vercel Spend Management |
| LLM | Anthropic API | Dedicated Console workspace with a monthly spend limit |
| Live data | TfL Unified API | Free key; CDN caching keeps call volume flat |
| Observability | Logfire + LangSmith free tiers | Free-tier quotas |

Hosting cost is expected to sit inside the Vercel Pro included usage. Details
in [Deployment](deployment.md).

## Removed from the stack

ADR 014 dropped the Kafka/Redpanda broker and the feed warehouse. ADR 015
then removed Postgres (Supabase), dbt, pgvector, the RAG layer (LlamaIndex,
PyMuPDF, Bedrock Titan embeddings), Pydantic AI, AWS Bedrock, and the
Lightsail + Caddy deploy. They remain in git history.

## What we explicitly avoid

These are not oversights. They are deliberate, motivated by the *lean by
default* principle in [`CLAUDE.md`](https://github.com/hcslomeu/tfl-monitor/blob/main/CLAUDE.md).

!!! danger "Anti-patterns"
    - **Multiple `pyproject.toml`s.** One root, one source of truth.
    - **Sidecar observability stacks.** No Prometheus / Grafana / OTel collector; Logfire and LangSmith cover what we need.
    - **Single-implementation abstractions.** No `LLMProvider` for one Claude client, no repository layer for one HTTP API.
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
    uv run task test            # pytest (integration tests excluded)
    uv run task api             # uvicorn with reload on :8000
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
    make bootstrap # install Python + Node deps, create .env
    make check     # lint + tests + TS build, chained
    make api       # run the API locally with .env loaded
    ```
