# TM-F2 — Plan

**WP title:** Production wiring — frontend on the real API
**Phase:** 2 / Plan
**Date:** 2026-05-15
**Author:** Claude (Opus 4.7)
**Predecessor:** `.claude/specs/TM-F2-research.md`

## Goal recap

Move the production dashboard at `https://tfl-monitor.humbertolomeu.com`
off mocks and onto the live FastAPI deployment, with CORS, DNS, TLS, and
env vars correctly wired. Mocks stay only for surfaces whose backend
support is intentionally out of scope (see §3 widget matrix).

## 1. Widget → data dependency matrix

Audit of `web/app/page.tsx` plus every component rendered from it.

| Surface | Component | Data dependency | Today | Action in TM-F2 |
| --- | --- | --- | --- | --- |
| Header summary | `TopNav` | derived from `LineStatus[]` | follows `getStatusLive` | falls through — no own fetcher |
| Line grid (14 tiles) | `LineGrid` | `getStatusLive` (`/api/v1/status/live`) | fetcher with `USE_MOCKS` short-circuit | drop short-circuit; live by default |
| Selected line panel | `LineDetail` | derived from status + disruptions | follows `getStatusLive` + `getRecentDisruptions` | falls through |
| Selected-line disruption banner | `LineDetail.disruption` | `getRecentDisruptions` (`/api/v1/disruptions/recent`) | fetcher with `USE_MOCKS` short-circuit | drop short-circuit; live by default |
| Bus banner | `BusBanner` | `MOCK_BUSES` (no fetcher) | permanently mocked | **stay mocked**; the upstream mart `mart_bus_metrics_daily` joins on the empty `ref.lines` table, so a live wire would render zero rows (see PROGRESS §TM-D3 caveat) |
| News & reports panel | `NewsReports` | `MOCK_NEWS` (no fetcher, no contract endpoint) | permanently mocked | **stay mocked**; no backing endpoint exists in `contracts/openapi.yaml` |
| Chat panel | `ChatPanel` | `MOCK_CHAT_SEED` only (no API call) | echoes user input locally; the SSE wiring shipped by TM-E3 was lost in the TM-E5 rewrite | **rewrite to stream** against `streamChat()` from `lib/api/chat-stream.ts`, modelled after the deleted `ChatView` (`tests/git-deleted/components/chat-view.tsx` — recover via `git show 9cb1b15:web/components/chat-view.tsx` or equivalent SHA) |

Endpoints not consumed by the current dashboard (not in TM-F2 scope):
`/api/v1/status/history`, `/api/v1/lines/{line_id}/reliability`,
`/api/v1/buses/{operator}/punctuality`,
`/api/v1/chat/history`. These remain unreachable from the UI; their
contract tests stay green via OpenAPI drift checks. Re-introducing them
to the dashboard is a future WP.

## 2. Open questions — resolutions

Inheriting the six decisions from research §5 and locking each to a
concrete Phase-3 action.

### 2.1 Public API hostname — DEFERRED (locked 2026-05-16)

**Decision:** keep `tfl-monitor-api.humbertolomeu.com`. The originally
proposed migration to `api.tfl-monitor.humbertolomeu.com` is out of
TM-F2 scope.

**Rationale:** the existing hostname is live, the Let's Encrypt cert is
already issued, Cloudflare DNS already resolves. Migrating costs cert
order wait + DNS propagation + risk of a Caddy rate-limit on the new
order + doc churn across three files (`infra/README.md`,
`.claude/specs/TM-A5-plan.md`, `.claude/adrs/006-aws-deploy.md`). The
only benefit is aesthetic conformance with the alpha-whale
`<service>.humbertolomeu.com` pattern — a portfolio reviewer sees a
legible API hostname either way. The migration is reversible in a
future cosmetics WP if it ever ranks above other work.

**Action in TM-F2:** none. Phase 3.1 below drops all hostname-related
steps and ships only the CORS allow-list change.

### 2.2 CORS allow-list

**Decision (research §5.3):** ship the regex form to cover Vercel
previews — preview deploys land on
`https://tfl-monitor-<hash>-<scope>.vercel.app` and there is no
deterministic list. Pin the production hostnames explicitly so a typo
in the regex cannot silently widen the allow-list.

**Phase-3 edit** (`src/api/main.py:112-121`):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tfl-monitor.vercel.app",
        "https://tfl-monitor.humbertolomeu.com",
    ],
    allow_origin_regex=r"^https://tfl-monitor-[a-z0-9-]+\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "Authorization"],
)
```

Methods + headers are narrowed from `*` because the API surface is
GET-only except for the SSE `POST /api/v1/chat/stream` — there is no
reason to advertise PUT/DELETE/PATCH preflight.

**Success signal:** a preflight `OPTIONS` from
`https://tfl-monitor.humbertolomeu.com` returns
`access-control-allow-origin: https://tfl-monitor.humbertolomeu.com`
and a preview-style origin (e.g.
`https://tfl-monitor-abc123-humberto.vercel.app`) is also echoed back.
`curl -i -X OPTIONS -H "Origin: ..." -H "Access-Control-Request-Method: GET" https://api.tfl-monitor.humbertolomeu.com/api/v1/status/live`.

### 2.3 Frontend custom-domain DNS

**Decision (research §5.4):** verify with `dig`. If missing, add the
CNAME on Cloudflare and wait for the Vercel certificate to issue.

**Phase-3 steps:**

1. `dig +short tfl-monitor.humbertolomeu.com` — expected
   `cname.vercel-dns.com.` and a Vercel anycast IP.
2. If the record is missing, add CNAME `tfl-monitor →
   cname.vercel-dns.com` on Cloudflare (DNS-only, no proxy — Vercel's
   automatic cert issuance fails through Cloudflare's proxy).
3. Re-run `dig` until the record propagates, then load the apex in a
   browser and confirm the lock icon (Vercel-issued cert).

This step is a no-op if PR #62 / TM-E4 closure already added the CNAME.
Verifying in Phase 3 is cheap; assuming-and-skipping is not.

### 2.4 `USE_MOCKS` semantics

**Decision (research §5.6):** invert to opt-in. `USE_MOCKS = true` only
when `NEXT_PUBLIC_USE_MOCKS === "true"`. The default (unset / any other
value) means live data.

**Phase-3 edit** (`web/lib/env.ts:10`):

```ts
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";
```

Then on Vercel:

- Production target: **unset** `NEXT_PUBLIC_USE_MOCKS` entirely
  (`vercel env rm NEXT_PUBLIC_USE_MOCKS production`).
- Preview target: same — unset.
- Local dev: contributors who want offline mode set
  `NEXT_PUBLIC_USE_MOCKS=true` in `web/.env.local` (the file is in
  `.gitignore`).

`web/.env.example` gains the variable with a comment explaining the
opt-in semantics.

**Success signal:** after the env var is unset and the build redeploys,
`curl -s https://tfl-monitor.humbertolomeu.com/_next/data/<id>/index.json`
(or equivalent server inspection) returns a response with `valid_from`
timestamps drawn from real Postgres rows, not the `MOCK_LINES`-derived
fixtures.

### 2.5 LLM cost / rate-limit

**Decision (research §5.5):** Haiku 4.5 is the active routing model
(see PROGRESS §TM-A5: "Bedrock Claude 4.5 (Sonnet + Haiku) via
eu-west-2 cross-region inference profiles"). No rate-limit work in
TM-F2 scope. Documented here so a future cost spike has a clear
"why didn't we add rate-limiting" pointer.

### 2.6 `NEXT_PUBLIC_API_URL` on Vercel

Hostname stays `tfl-monitor-api.humbertolomeu.com` (see §2.1). Update
the Vercel project env var on both targets:

- Production target:
  `NEXT_PUBLIC_API_URL=https://tfl-monitor-api.humbertolomeu.com`.
- Preview target: same value.

Set via `pnpm dlx vercel env add` (production-only form is known to
work — see napkin §"Shell & Command Reliability" item 10 for the
REST-API workaround if the CLI rejects the preview form).

`web/lib/api-client.ts` keeps `DEFAULT_API_URL = "http://localhost:8000"`
unchanged — that fallback only fires when the env var is unset, which
on Vercel is now a deploy-time bug surfaced by the smoke test, not a
silent prod misroute.

## 3. Phase-3 sub-phases

Each sub-phase ends with a verification gate. **No sub-phase advances
on a non-zero gate.** Commit at the end of each sub-phase so the PR is
reviewable per logical step.

### Phase 3.1 — Backend CORS allow-list

**Touches:** `src/api/main.py`, plus a new
`tests/api/test_cors.py` exercising the regex.

**Steps:**

1. Edit `src/api/main.py` CORS block per §2.2 (pinned list + regex,
   narrowed methods + headers).
2. Write a unit test that asserts:
   - `localhost:3000` echoes.
   - `https://tfl-monitor.humbertolomeu.com` echoes.
   - A representative preview origin (`https://tfl-monitor-abc123-humberto.vercel.app`)
     echoes (regex hit).
   - `https://tfl-monitor.vercel.app.attacker.com` does **not** echo
     (regex anchored — proves the negative).
3. Deploy backend via the existing GHA `deploy.yml` once the PR
   merges to `main`.

**Verification gate:**

- `uv run task lint && uv run task test && uv run bandit -r src --severity-level high` exit 0.
- After deploy: `curl -i -X OPTIONS -H "Origin: https://tfl-monitor.humbertolomeu.com" -H "Access-Control-Request-Method: GET" https://tfl-monitor-api.humbertolomeu.com/api/v1/status/live` → 200 with `access-control-allow-origin: https://tfl-monitor.humbertolomeu.com`.
- After deploy: `curl -i -X OPTIONS -H "Origin: https://tfl-monitor-abc123-humberto.vercel.app" -H "Access-Control-Request-Method: GET" https://tfl-monitor-api.humbertolomeu.com/api/v1/status/live` → 200 with the preview origin echoed (regex hit).

### Phase 3.2 — Frontend default flip + env wiring

**Touches:** `web/lib/env.ts`, `web/.env.example`, Vercel project env
vars (production + preview targets).

**Steps:**

1. Edit `web/lib/env.ts` per §2.4 (`=== "true"`).
2. Update `web/.env.example` to document the new opt-in semantics with
   a one-line comment.
3. Vercel: unset `NEXT_PUBLIC_USE_MOCKS` on both targets; set
   `NEXT_PUBLIC_API_URL=https://tfl-monitor-api.humbertolomeu.com` on
   both targets per §2.6.
4. Trigger a fresh Vercel build (push to `main` after Phase 3.1 is in,
   OR `pnpm dlx vercel --cwd web redeploy <last-prod-url>` if the
   timing requires a manual kick).

**Verification gate:**

- `pnpm --dir web lint && pnpm --dir web test && pnpm --dir web build`
  exit 0 (USE_MOCKS short-circuits still pass their existing tests —
  they import `USE_MOCKS` from `lib/env`, which the test runner
  controls via `vi.stubEnv` or by re-importing after setting the env
  var; verify in step 1 whether existing tests need an update).
- After redeploy, the production HTML at
  `https://tfl-monitor.humbertolomeu.com/` shows real status data
  (timestamps not pinned to "2 minutes ago", line names matching the
  current TfL operational state).
- DevTools → Network: the page makes XHRs to
  `https://tfl-monitor-api.humbertolomeu.com/api/v1/status/live` and
  `/api/v1/disruptions/recent`. Response status 200, response body
  matches the `LineStatus` / `Disruption` schemas.
- No CORS errors in the browser console.

### Phase 3.3 — Drop the in-fetcher `USE_MOCKS` short-circuits

**Touches:** `web/lib/api/status-live.ts`,
`web/lib/api/disruptions-recent.ts`, related tests.

**Rationale:** with §3.2 done, `USE_MOCKS` is opt-in. The short-circuit
branches in the two fetchers still exist for local dev offline mode.
Leaving them in keeps the dual code path forever; removing them
collapses the API to a single live-only branch and the offline-dev
workflow uses Vercel preview deploys + real backend instead.

This sub-phase is **optional** and lands only if the author confirms
the local-dev workflow can absorb the loss of offline mode. Default
recommendation: **keep the short-circuits** (lean by default — they
cost six lines per fetcher and unblock the offline demo when the
backend is down).

**If chosen, steps:**

1. Delete `if (USE_MOCKS) { … }` blocks in both fetchers.
2. Delete the helper functions (`lineSummaryToLineStatus`,
   `toMockDisruption`) and the `MOCK_LINES` / `MOCK_DISRUPTION` imports.
3. Delete the `*.mock.test.ts` files
   (`status-live.mock.test.ts`, `disruptions-recent.mock.test.ts`).
4. Delete `web/lib/mocks/lines.ts` and `web/lib/mocks/disruptions.ts`
   if and only if no other importer remains (`pnpm --dir web build`
   surfaces unused-import errors via Biome).

**Verification gate:** `pnpm --dir web lint && pnpm --dir web test &&
pnpm --dir web build` exit 0; live dashboard still renders.

### Phase 3.4 — Chat panel SSE rewrite

**Touches:** `web/components/dashboard/chat-panel.tsx`, new tests under
`web/components/dashboard/__tests__/chat-panel.test.tsx`,
`web/app/page.tsx` (drop `MOCK_CHAT_SEED` import if no longer needed).

**Rationale:** today the chat panel is decorative. The SSE wiring that
TM-E3 shipped under `web/components/chat-view.tsx` was lost in the
TM-E5 rewrite. TM-F2's "off mocks" claim is hollow without the chat
panel actually streaming.

**Steps:**

1. Recover the TM-E3 streaming logic. The `streamChat()` async
   generator at `web/lib/api/chat-stream.ts` is still on `main` and
   ready to use — only the React component is missing.
2. Rewrite `ChatPanel.send()` to:
   - mint a stable `threadId` per mount (`useRef(crypto.randomUUID())`),
   - push the user message and an empty in-flight assistant message
     into `messages`,
   - call `streamChat({ thread_id, message }, signal)` and iterate
     frames,
   - on `frame.type === "token"`, append to the trailing assistant
     bubble,
   - on `frame.type === "tool"`, surface "Using tool: …" inline,
   - on `frame.type === "end"`, finalise; if `end:"error"`, mark the
     bubble `data-errored="true"`,
   - on `ApiError` / network failure, roll back the user + assistant
     bubble pair and show a top-of-card `Alert role="alert"` per the
     TM-E3 pattern.
3. Drop `MOCK_CHAT_SEED` from `app/page.tsx` — empty initial state on
   first mount is fine; seed messages were a Storybook-style demo crutch.
4. Tests: port the five TM-E3 `ChatView` cases (empty shell, token
   stream, tool-status lifecycle, 503 alert + rollback, mid-stream
   `end:error` flagging).

**Verification gate:**

- `pnpm --dir web lint && pnpm --dir web test && pnpm --dir web build`
  exit 0.
- Manual: visit the production URL, type "What's the Northern line
  doing?", hit Send, watch tokens stream in, watch any tool calls
  surface inline.
- LangSmith dashboard shows a fresh trace for the request.

### Phase 3.5 — End-to-end smoke + audit

**Touches:** none. This is a verification-only sub-phase.

**Steps:**

1. Run the full `make check` gate (`uv run task lint`, `uv run task
   test`, `pnpm --dir web lint`, `pnpm --dir web test`,
   `pnpm --dir web build`, bandit). All exit 0.
2. Load `https://tfl-monitor.humbertolomeu.com/` in Chrome + Firefox.
   Confirm: 14 live tiles, real timestamps, disruption banner if
   present, chat streams, console clear.
3. Inspect the response headers on the prod page:
   `X-Frame-Options: DENY`, `Strict-Transport-Security: max-age=63072000; …`.
4. Drop a Playwright smoke if the existing `web/tests/e2e/` already has
   the harness — otherwise document a manual checklist in the PR body.
5. Update `PROGRESS.md` with the TM-F2 completion row.
6. Update `.claude/current-wp.md` to reflect TM-F2 done.

## 4. Pre-push verification gate (per CLAUDE.md "Before committing")

All four must exit 0 before the PR opens:

```bash
uv run task lint
uv run task test
uv run bandit -r src --severity-level high
make check
```

Plus the frontend gate explicitly:

```bash
pnpm --dir web lint
pnpm --dir web test
pnpm --dir web build
```

If any returns non-zero, the failing tool's output is the next item to
fix — do not move on. Skipping is how merge-blocker bugs leak in
(napkin §"Execution & Validation" item 6).

## 5. What we are NOT doing in TM-F2

- **No new dashboard widgets** for the four unreached endpoints
  (`status/history`, `lines/{id}/reliability`, `buses/.../punctuality`,
  `chat/history`). They stay in `contracts/openapi.yaml`, tested by the
  drift suite, but not surfaced in the UI. Adding a reliability
  widget, a 24h-history strip, or a bus-punctuality card is a separate
  WP (TM-Fx).
- **No rate-limiting / cost guard.** Haiku-4.5 already absorbs the cost
  exposure; revisit only if observed cost diverges materially from
  estimate (research §5.5).
- **No CSP header.** `next.config.ts` security headers stay as
  TM-E4 shipped them; CSP is a polish item for TM-F1.
- **No CDN / caching layer in front of the API.** All live traffic
  goes Caddy → uvicorn directly. Lightsail's bandwidth budget at this
  traffic scale is non-issue.
- **No removal of `BusBanner` / `NewsReports` from the UI.** They stay
  mocked; that is a deliberate scope cap, not an unfinished cutover.
  The portfolio reviewer can read this plan to understand the
  decision.
- **No removal of `web/lib/mocks/lines.ts` /
  `web/lib/mocks/disruptions.ts`.** Phase 3.3 is opt-in only — default
  recommendation is to keep them so the offline-dev workflow survives.
- **No SSH-based live audit of producers/consumers.** The cron-driven
  `dbt build` is the visibility boundary; if marts are empty, that is
  a TM-Ax issue, not TM-F2's.
- **No upgrade of `psycopg`/`anthropic`/`langgraph` deps.** Stack lock
  unchanged.

## 6. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| CORS regex typo silently widens the allow-list | Pin production hostnames explicitly + add an integration test that asserts the regex rejects `https://tfl-monitor.vercel.app.attacker.com` |
| Vercel preview URL pattern changes (Vercel breaking change) | Audit `vercel deploy --target preview` output before merging; if the URL shape changes, regenerate the regex |
| Cloudflare CNAME for `api.tfl-monitor` proxied by accident | Confirm DNS-only flag in the Cloudflare UI screenshot in the PR body; orange-cloud breaks HTTP-01 |
| Caddy fails to issue cert for the new hostname (rate limit, port 80 closed) | Pre-flight check that port 80 reaches the Lightsail static IP (`curl -i http://13.41.145.33`); review Caddy logs immediately after reload |
| Local-dev contributors confused by `USE_MOCKS` inversion | `.env.example` carries an inline comment; commit message + PR body call out the breaking-default change |
| Chat panel rewrite regresses the TM-E5 layout (chat sticks 1/3 on `lg+`) | Reuse the existing CSS / DOM structure; only swap the `send()` body. Snapshot the existing `chat-card` markup before edit |

## 7. Confirmation gate — locked 2026-05-16

The author delegated each decision to the assistant's recommendation.
Final scope:

| # | Question | Decision | Rationale |
| --- | --- | --- | --- |
| 1 | API hostname migration | **NO** — keep `tfl-monitor-api.humbertolomeu.com` | Cert + DNS already live; migration cost > aesthetic benefit. Reversible later. |
| 2 | CORS regex + pinned list per §2.2 | **YES** | Pinned list locks prod, regex unblocks Vercel preview deploys (recruiter clicks on PR previews work). |
| 3 | `USE_MOCKS` inversion per §2.4 | **YES** | Current default is production-hostile; flip costs 1 line, surfaces missing env at deploy time. |
| 4 | Drop short-circuits in fetchers (Phase 3.3) | **NO** — keep | Six lines per fetcher pay rent: unblock `make check` offline + demo without backend. Lean-by-default is not "delete working code". |
| 5 | Chat-panel SSE rewrite (Phase 3.4) | **YES** | "Off mocks" claim is hollow with a decorative chat. `streamChat()` already on main; TM-E3 PR #46 is the reference. |

**Phase-3 scope:** 3.1 (CORS only — hostname work dropped) + 3.2 + 3.4
+ 3.5. Phase 3.3 deferred indefinitely.

## 8. Estimated effort

| Sub-phase | Estimate |
| --- | --- |
| 3.1 Backend CORS | 30-40 min (config + test + deploy wait) |
| 3.2 Frontend default flip + env wiring | 30 min |
| 3.4 Chat SSE rewrite | 90-120 min (recovery + tests) |
| 3.5 E2E smoke + audit | 30 min |
| **Total** | **~3h** |

Wall-clock total including Vercel rebuild + GHA deploy: half a working
day.
