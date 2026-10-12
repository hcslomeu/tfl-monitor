# Setup

How to run tfl-monitor locally and how it is deployed. The app is a stateless
FastAPI API plus a Next.js dashboard, both on Vercel. There is no database or
other local service to start (ADR 015).

- [1. Prerequisites](#1-prerequisites)
- [2. Accounts and keys](#2-accounts-and-keys)
- [3. Local development](#3-local-development)
- [4. Checks and tests](#4-checks-and-tests)
- [Deploy](#deploy)
- [Troubleshooting](#troubleshooting)

---

## 1. Prerequisites

| Tool | Version | Install |
|---|---|---|
| `uv` | 0.5+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 22 LTS | via `fnm`, `nvm`, or `asdf` |
| `pnpm` | 10 | `corepack enable pnpm` |
| `make` | recent | native on macOS/Linux; Windows: WSL2 |
| `git` | 2.40+ | native |
| `gh` CLI | optional | `https://cli.github.com/` |

`uv` installs Python 3.12 for you if it is missing.

## 2. Accounts and keys

Keys go in your local `.env` (never committed) and, for production, in the
Vercel project settings.

| Service | Needed for | How to get it | Cost |
|---|---|---|---|
| TfL Unified API | Dashboard and every agent tool | `api-portal.tfl.gov.uk/signup`, then subscribe to the "500 requests per min" product and copy the primary key | Free |
| Anthropic API | Chat | `console.anthropic.com` (see below) | Pay as you go, capped |
| LangSmith | Agent traces (optional) | `smith.langchain.com`, free tier | Free |
| Logfire | Request spans (optional) | `logfire.pydantic.dev`, free tier; create a project and a write token | Free |
| Vercel | Deploy only | `vercel.com`, Pro plan for the API project | Plan fee |

**Anthropic spend cap.** In the Anthropic Console, create a dedicated
workspace for tfl-monitor, set a monthly spend limit on it, and issue the API
key from that workspace. The limit is the only LLM cost guard: when it is
reached, the chat stream tells the user the assistant is unavailable and the
dashboard keeps working.

**LangSmith.** Create an API key and use project name `tfl-monitor`. LangGraph
sends traces automatically when `LANGSMITH_TRACING=true` is set before the
process starts.

**Logfire.** Without `LOGFIRE_TOKEN`, Logfire runs as a no-op, so local
development and tests need no credentials.

## 3. Local development

### 3.1 Bootstrap

```bash
git clone git@github.com:hcslomeu/tfl-monitor.git
cd tfl-monitor
make bootstrap    # uv sync + pnpm --dir web install + cp .env.example .env
```

### 3.2 Environment variables (`.env`)

| Variable | Required | Purpose |
|---|---|---|
| `TFL_APP_KEY` | yes | TfL key. Unset: `/status/live` and `/disruptions/recent` return `503`, agent has no tools |
| `ANTHROPIC_API_KEY` | for chat | Unset: `/chat/stream` returns `503`; the rest works |
| `CHAT_MODEL` | no | Model id override; default `claude-haiku-5-5` |
| `LOGFIRE_TOKEN` | no | Enables Logfire export |
| `LOGFIRE_SAMPLE_RATE` | no | Head sample rate, default `0.1` (warnings and slow traces are always kept) |
| `LANGSMITH_TRACING` | no | `true` to send agent traces |
| `LANGSMITH_API_KEY` | no | LangSmith key |
| `LANGSMITH_PROJECT` | no | `tfl-monitor` |
| `ENVIRONMENT` | no | Observability tag, `local` by default |
| `APP_VERSION` | no | Observability version tag |
| `TFL_DEBUG_PROXY` | no, local only | `1` exposes `/api/v1/debug/tfl/*` in Swagger to inspect raw TfL payloads. Never set in production |

### 3.3 Run the API

```bash
make api          # runs `uv run task api-debug`: uvicorn --reload with .env loaded
```

The API listens on <http://localhost:8000>; Swagger UI is at `/docs`.
Smoke test:

```bash
curl -s localhost:8000/health
curl -s localhost:8000/api/v1/status/live | head -c 400
curl -N -X POST localhost:8000/api/v1/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"thread_id": "local-1", "message": "How is the Victoria line right now?"}'
```

`uv run task api` starts uvicorn without loading `.env` (export the variables
yourself).

### 3.4 Run the frontend

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm --dir web dev    # http://localhost:3000
```

Or copy `web/.env.example` to `web/.env.local` and set the variables there.
`NEXT_PUBLIC_API_URL` falls back to `http://localhost:8000` when unset. Set
`NEXT_PUBLIC_USE_MOCKS=true` to render the dashboard from in-repo fixtures
without the API.

After changing `contracts/openapi.yaml`, regenerate the frontend types:

```bash
make openapi-ts   # writes web/lib/types.ts; CI fails if it drifts
```

### 3.5 Documentation site

```bash
uv sync --group docs
uv run task docs-serve    # http://127.0.0.1:8001
```

## 4. Checks and tests

```bash
uv run task lint    # ruff check + ruff format --check + mypy (strict)
uv run task test    # pytest, unit tests only
make check          # the two above, then pnpm --dir web lint, test, build
```

The integration test streams a real chat turn against live TfL and Anthropic,
so it needs both keys, spends LLM budget, and is opt-in:

```bash
uv run pytest -m "integration and slow" tests/integration/test_chat_stream.py -v
```

CI (`.github/workflows/ci.yml`) runs three jobs on every PR and on `main`:
`lint` (lint + Bandit, HIGH severity blocks), `test`, and `frontend` (Biome,
Vitest, Next build, OpenAPI type drift). Branch protection on `main` should
require all three.

---

## Deploy

Both halves deploy through the Vercel Git integration. There is no deploy
workflow in GitHub Actions and no server to SSH into.

| Vercel project | Root directory | Serves | Domain |
|---|---|---|---|
| `tfl-monitor-api` | repository root | FastAPI (`src/api/main.py`) as a Python function | `tfl-monitor-api.humbertolomeu.com` |
| `tfl-monitor` | `web` | Next.js dashboard | `tfl-monitor.humbertolomeu.com` |

### API project (`tfl-monitor-api`)

- Pro plan, Fluid compute on. Region `lhr1` comes from `vercel.json`.
- Entrypoint: `pyproject.toml` `[tool.vercel] entrypoint = "src.api.main:app"`.
  Vercel installs runtime dependencies from `uv.lock`.
- `vercel.json` sets `maxDuration: 300` (long SSE chat turns) and excludes
  `.claude/`, `.github/`, `docs/`, `scripts/`, `tests/`, `web/` and Markdown
  from the bundle.
- Environment variables (Production and Preview): `TFL_APP_KEY`,
  `ANTHROPIC_API_KEY`, optional `CHAT_MODEL`, `LOGFIRE_TOKEN`,
  `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`,
  `ENVIRONMENT` (e.g. `production`), `APP_VERSION`. Do not set
  `TFL_DEBUG_PROXY`.
- Set a Spend Management limit on the Vercel team to cap function usage.

### Frontend project (`tfl-monitor`)

- Root directory `web`, framework Next.js, pnpm.
- Environment variable: `NEXT_PUBLIC_API_URL=https://tfl-monitor-api.humbertolomeu.com`
  for Production and Preview. Leave `NEXT_PUBLIC_USE_MOCKS` unset.
- The API's CORS allowlist accepts the production origins and
  `tfl-monitor-*.vercel.app` previews; other origins are rejected.

### DNS

`humbertolomeu.com` is on Cloudflare. `tfl-monitor-api` and `tfl-monitor`
are CNAME records to Vercel, DNS only (grey cloud). Vercel issues the TLS
certificates.

### Release flow

1. Push a branch or open a PR: Vercel builds a preview deployment for each
   project; CI runs in GitHub Actions.
2. Merge to `main`: Vercel deploys production and aliases the custom domains.
3. Verify:

   ```bash
   curl -fsS https://tfl-monitor-api.humbertolomeu.com/health
   curl -sI https://tfl-monitor-api.humbertolomeu.com/api/v1/status/live | grep -i -E "cache-control|x-vercel-cache"
   ```

### Rollback

- Promote a previous production deployment in the Vercel dashboard (or
  `vercel rollback`).
- Or revert the merge commit on `main`; the next push redeploys.
- To change the chat model only, set `CHAT_MODEL` and redeploy.

More detail: [docs/deployment](https://hcslomeu.github.io/tfl-monitor/deployment/).
The previous AWS-hosted setup is described in ADR 006 and was retired by
ADR 015.

---

## Troubleshooting

**Live endpoints return `503`.** `TFL_APP_KEY` is not set in the process
environment. Locally, use `make api` (it loads `.env`); on Vercel, check the
project's environment variables and redeploy.

**Live endpoints return `502`.** TfL failed after the client's retries. The
`get_status_live_failed` / `get_recent_disruptions_failed` exception in
Logfire shows the upstream error; a `429` means the key's rate limit was
hit.

**Chat returns `503`.** `ANTHROPIC_API_KEY` is not set.

**Chat answers "The assistant is unavailable right now".** Anthropic rejected
the call: the workspace's monthly spend limit was reached, the key is
invalid, or the request was rate limited. The Logfire event
`chat_llm_rejected` carries the status code.

**Chat forgets earlier messages.** Conversation memory is per function
instance; a cold start or another instance starts the thread fresh. Expected.

**Browser shows a CORS error.** The page origin is not in the allowlist in
`src/api/main.py` (production domains, `http://localhost:3000`, and
`tfl-monitor-*.vercel.app` previews).

**Logfire dashboard is empty.** `send_to_logfire="if-token-present"` only
activates when `LOGFIRE_TOKEN` is present at process startup. Restart the
API after editing `.env`.

**LangSmith traces do not appear.** `LANGSMITH_TRACING=true` must be set
before the Python process starts.

**`make bootstrap` fails with `uv: command not found`.** `uv` is not on your
`PATH`. Reopen the terminal or add the install path the installer printed.
