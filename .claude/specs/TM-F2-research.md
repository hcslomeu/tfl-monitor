# TM-F2 — Research

**WP title:** Production wiring — frontend on the real API
**Phase:** 1 / Research (read-only)
**Date:** 2026-05-15
**Author:** Claude (Opus 4.7)

## Goal of TM-F2

Take the dashboard at `https://tfl-monitor.humbertolomeu.com` (Vercel) off
mocks and onto the live FastAPI deployment on the shared Lightsail box.
End state: every dashboard request hits real Postgres-backed data through
the production API, with CORS, DNS, TLS, and env vars correctly wired.

This file documents the current state. No implementation, no suggestions
for improvement — those land in `TM-F2-plan.md` (Phase 2).

## 1. Backend — FastAPI on Lightsail

### 1.1 Endpoints currently exposed (`src/api/main.py`)

| Method | Path | Operation id |
| --- | --- | --- |
| GET | `/health` | `get_health` |
| GET | `/api/v1/status/live` | `get_status_live` |
| GET | `/api/v1/status/history` | `get_status_history` |
| GET | `/api/v1/lines/{line_id}/reliability` | `get_line_reliability` |
| GET | `/api/v1/disruptions/recent` | `get_recent_disruptions` |
| GET | `/api/v1/buses/{operator}/punctuality` | `get_bus_punctuality` |
| POST | `/api/v1/chat/stream` | `post_chat_stream` (SSE) |
| GET | `/api/v1/chat/history` | `get_chat_history` |

All operation ids match the contracts in `contracts/openapi.yaml` (per
TM-C2 / TM-D1 conventions).

### 1.2 CORS configuration (`src/api/main.py:112-121`)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tfl-monitor.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Gaps relative to TM-F2 goal:

- `https://tfl-monitor.humbertolomeu.com` (custom production domain) is
  not listed.
- Vercel preview deploys land on `tfl-monitor-<hash>-<scope>.vercel.app`;
  the canonical entry only covers the canonical hostname.

### 1.3 Hosting topology

From `infra/README.md` + `infra/docker-compose.prod.yml`:

- Host: AWS Lightsail eu-west-2, Ubuntu 24.04, static IP `13.41.145.33`.
- App dir: `/opt/tfl-monitor/`.
- Three docker services: `api` (FastAPI, container `tfl-monitor-api-1`,
  port `8000` on the internal docker network `caddy_net`), `producers`
  (ingestion runner), `consumers` (ingestion runner). No Airflow in prod;
  dbt runs via host cron (`infra/cron.d/tfl-monitor`, every 6h).
- Reverse proxy: shared Caddy at `/opt/caddy/`, joins `caddy_net`,
  terminates TLS with Let's Encrypt staging certs (per ADR 006 / TM-A5
  plan §3).

### 1.4 Public hostname — **discrepancy with TM-F2 intent**

The wiring committed today already terminates on a different hostname
than the one chosen for TM-F2:

| Source | Hostname |
| --- | --- |
| `infra/caddyfile.snippet:9` (deployed) | `tfl-monitor-api.humbertolomeu.com` |
| `infra/README.md` | `tfl-monitor-api.humbertolomeu.com` |
| `.claude/specs/TM-A5-plan.md` | `tfl-monitor-api.humbertolomeu.com` |
| TM-F2 user decision (this session) | `api.tfl-monitor.humbertolomeu.com` |

Implication: either (a) accept the existing hostname (zero new infra) or
(b) add a second Caddy site block + Cloudflare record for the new
sub-sub-domain and either keep both or drop the old one. The Phase-2
plan must resolve this before any code change.

### 1.5 Observability

- LangSmith: `LANGSMITH_TRACING=true`, project `tfl-monitor`, configured
  in `.env` on the Lightsail box. Captures LangGraph agent traces.
- Logfire: `configure_observability(app)` at `src/api/main.py:110`
  instruments FastAPI + Postgres + HTTPX. Traces visible in Logfire
  hosted dashboard.

## 2. Frontend — Next.js on Vercel

### 2.1 Vercel project

- Name: `tfl-monitor` (project id `prj_FA25p2XsTcQ2777DzMZvlr03iWAb`).
- Linked dir: `web/`.
- Production URL: `https://tfl-monitor.vercel.app`.
- Custom domain: `https://tfl-monitor.humbertolomeu.com` (status to
  confirm in Phase 2 — Cloudflare CNAME may still need to be created).
- Vercel CLI is **not installed** on this workstation, so the env-var
  state could not be enumerated programmatically in Phase 1. Confirmed
  via the handover note: `NEXT_PUBLIC_USE_MOCKS=true` is currently set
  on both preview and production targets.

### 2.2 Runtime flags

```ts
// web/lib/env.ts
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS !== "false";
```

Default-on: any value other than the literal string `"false"` (including
the var being unset) keeps mocks active. To go live the Vercel env must
be explicitly `"false"`.

```ts
// web/lib/api-client.ts
const DEFAULT_API_URL = "http://localhost:8000";
function baseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL;
}
```

Same `DEFAULT_API_URL` is duplicated in `web/lib/api/chat-stream.ts:16`.

### 2.3 API client surface

Three feature fetchers under `web/lib/api/`:

- `status-live.ts` — calls `GET /api/v1/status/live`; mock-aware,
  projects `MOCK_LINES` to the `LineStatus` schema.
- `disruptions-recent.ts` — calls `GET /api/v1/disruptions/recent`.
- `chat-stream.ts` — `POST /api/v1/chat/stream` (SSE via fetch +
  `ReadableStream` + `SSEParser`).

Mock fixtures under `web/lib/mocks/`: `lines.ts`, `disruptions.ts`,
`buses.ts`, `chat.ts`, `news.ts`, `reliability.json`.

Gap: there are no client-side fetchers for `status/history`,
`reliability`, `buses/punctuality`, `chat/history`. The dashboard
currently consumes only the three endpoints above; the rest of the
OpenAPI surface is unreachable from the live UI. Whether TM-F2 needs to
add fetchers depends on which dashboard widgets must come off mocks —
to be settled in Phase 2.

### 2.4 Security headers

`web/next.config.ts` already sets `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy`,
`Permissions-Policy`, `Strict-Transport-Security`. No CSP — out of scope
for TM-F2 unless the live-API switch breaks something.

## 3. Data layer — producers + warehouse

### 3.1 Producers / consumers

`infra/docker-compose.prod.yml` declares `producers` and `consumers`
services running `python -m ingestion.run_producers` /
`python -m ingestion.run_consumers`, both with
`restart: unless-stopped`. They join the internal `tfl-monitor` docker
network and talk to Redpanda Cloud (SASL credentials in `.env`).

Health of these services on the live box cannot be confirmed without
SSH; Phase 2 must verify with
`docker ps --filter name=tfl-monitor-` and a sample
`docker logs tfl-monitor-producers-1 --tail 50`.

### 3.2 Warehouse (Supabase Postgres)

The dbt models materialise into `analytics.stg_*` and downstream marts.
Cron job at `infra/cron.d/tfl-monitor:12` runs `dbt build` every six
hours via `scripts/cron-dbt-run.sh`. Freshness has to be verified in
Phase 2 against the production `DATABASE_URL`.

## 4. CI / deploy pipeline

Three GitHub workflows in `.github/workflows/`:

- `ci.yml` — lint + test + bandit for backend + frontend.
- `deploy.yml` — production deploy to Lightsail (rsync +
  `docker compose up -d --build`) on every `main` push touching backend
  paths.
- `docs.yml` — documentation build.

Neither workflow sets `NEXT_PUBLIC_API_URL` or `NEXT_PUBLIC_USE_MOCKS`;
those live exclusively in Vercel project env vars. Vercel re-builds on
every `main` push to `web/`, so flipping the env var alone is enough —
no workflow edit needed.

## 5. Open questions — decisions captured 2026-05-15

1. **Public API hostname → `api.tfl-monitor.humbertolomeu.com`.** Matches
   the alpha-whale convention of `<service>.humbertolomeu.com` once the
   sub-sub-domain split is taken into account (the flat
   `tfl-monitor.humbertolomeu.com` is already claimed by the Vercel
   frontend). Phase 3 edits `infra/caddyfile.snippet`, adds the
   Cloudflare A record, and retires
   `tfl-monitor-api.humbertolomeu.com`.
2. **Scope of widgets going live → bounded by what the dashboard
   actually consumes.** Phase 2 enumerates every widget on the live
   `app/page.tsx` (and any sub-routes), maps each to its data
   dependency, and drops mocks only for the endpoints that back a
   rendered widget. Mocks stay for anything not displayed today.
3. **CORS allow-list → deferred to execution.** Phase 3 picks the final
   form (hard-coded list vs `allow_origin_regex` for Vercel previews)
   while wiring the new hostname; both options stay open in the plan.
4. **Custom-domain DNS state.** Verified during Phase 2 with
   `dig +short tfl-monitor.humbertolomeu.com`. If the CNAME to
   `cname.vercel-dns.com` is missing, it is added on Cloudflare as a
   prerequisite step in Phase 3.
5. **LLM cost → Haiku 4.5, no rate-limit in TM-F2.** Chat already runs
   on Haiku in production, so the per-call cost is ~10x lower than
   Sonnet. Rate-limiting is therefore not a blocker for the cutover and
   is explicitly out of scope for this WP; revisit if usage spikes.
6. **`USE_MOCKS` default → invert to opt-in.** Current
   `process.env.NEXT_PUBLIC_USE_MOCKS !== "false"` is production-hostile:
   any environment that forgets to set the flag falls back to mocks. The
   plan flips the rule to `=== "true"`, so mocks must be explicitly
   enabled per env and live data is the default. Vercel production and
   preview targets get the flag unset; local dev can set it explicitly
   to keep the offline workflow.

## 6. Files / surfaces that will likely change in Phase 3

(Listed here for situational awareness; do not edit in Phase 1.)

- `src/api/main.py` — CORS allow-list.
- `infra/caddyfile.snippet` + Cloudflare DNS — if hostname migrates.
- `web/lib/api-client.ts`, `web/lib/api/chat-stream.ts` — possibly drop
  the duplicated `DEFAULT_API_URL` if Phase 2 chooses to unify; will
  also need an `apiFetch` retry / timeout policy review for live
  conditions.
- Vercel project env vars: `NEXT_PUBLIC_API_URL`,
  `NEXT_PUBLIC_USE_MOCKS` (preview + production).
- Optional new fetchers under `web/lib/api/` for endpoints still on
  mocks, depending on widget scope.

## 7. Verification commands to run in Phase 2

```bash
# DNS state
dig +short tfl-monitor-api.humbertolomeu.com
dig +short api.tfl-monitor.humbertolomeu.com
dig +short tfl-monitor.humbertolomeu.com

# API reachability (from a Vercel-class network, not localhost)
curl -i https://tfl-monitor-api.humbertolomeu.com/health
curl -i https://tfl-monitor-api.humbertolomeu.com/api/v1/status/live

# Producers / data freshness (on Lightsail)
ssh ubuntu@13.41.145.33 'docker ps --filter name=tfl-monitor-'
ssh ubuntu@13.41.145.33 'docker logs tfl-monitor-producers-1 --tail 50'

# Warehouse freshness (against Supabase)
psql "$DATABASE_URL" -c "select max(valid_to) from analytics.stg_line_status;"

# Vercel env enumeration (workstation needs vercel CLI installed)
pnpm dlx vercel env ls --cwd web
```

## 8. What we are NOT doing in Phase 1

- No edits to source, infra, or env vars.
- No SSH to the live box; observations limited to what is in the repo.
- No decision on the open questions in §5 — those belong to the plan.
