# web/

Next.js 16 dashboard for tfl-monitor — single-page `/` collapses live network
status, active and upcoming disruptions, a network-pulse tile, and the agent
chat into one client-side dashboard. Types regenerated from the OpenAPI
contract.

## Stack

- **Next.js 16** App Router on React 19
- **Tailwind CSS 4** (PostCSS pipeline)
- **shadcn/ui** — Radix Nova preset
- **Biome** — sole linter + formatter (no ESLint, no Prettier)
- **Vitest + React Testing Library** — sole test runner
- TypeScript types regenerated from `contracts/openapi.yaml` via
  `make openapi-ts` (writes `web/lib/types.ts`)
- **pnpm** — sole package manager (no npm, no yarn)

## Layout

```text
web/
├─ app/                       # App Router routes
│  ├─ page.tsx                # One-pager orchestrator (/)
│  └─ __tests__/page.test.tsx # Integration test
├─ components/
│  ├─ chat-view.tsx           # SSE-streaming chat
│  ├─ about-sheet.tsx         # Header "About" sheet
│  ├─ dashboard/              # Four dashboard cards + ChatPanel
│  └─ ui/                     # shadcn primitives
├─ lib/
│  ├─ api/                    # Client-side fetchers
│  ├─ hooks/use-auto-refresh.ts # Visibility-aware polling
│  ├─ labels.ts               # MODE_LABELS (TfL-brand)
│  ├─ sse-parser.ts           # 60-line stateful SSE parser
│  └─ types.ts                # generated — do not edit
├─ next.config.ts             # Security headers + 308 redirects
└─ biome.json                 # Single config for lint + format
```

## Quickstart

```bash
pnpm --dir web install        # only needed if you skipped `make bootstrap`
pnpm --dir web dev            # dev server on :3000
pnpm --dir web lint           # Biome check
pnpm --dir web test           # Vitest run
pnpm --dir web build          # Next production build
```

`make check` at the repo root chains lint + test + build for both Python and
TypeScript.

## Surface and wiring

The page is a single client component (`app/page.tsx`) that mounts two
`useAutoRefresh` polls — `/api/v1/status/live` every 30 s and
`/api/v1/disruptions/recent` every 5 min — and fans the data into:

| Surface | Source | Highlights |
|---------|--------|------------|
| `<NetworkStatusCard>` | live status | Mode tabs (Tube / Elizabeth / Overground / DLR / Tram·River·Cable / Bus) persisted in `localStorage` |
| `<HappeningNowCard>` | recent disruptions | RealTime + Incident only, sort `last_update DESC`, destructive Alert on closure |
| `<ComingUpCard>` | recent disruptions | PlannedWork only, sort `created ASC`, cap 5 |
| `<NetworkPulseTile>` | live status | Severe / degraded / good / other tally with TfL-correct semantics |
| `<ChatPanel>` | `/api/v1/chat/stream` (POST SSE) | Sticky aside on `lg+`, FAB-triggered Drawer on `<lg` |

Legacy `/disruptions`, `/reliability`, `/ask` issue permanent 308 redirects to `/`.

Each fetcher imports its operation type from `lib/types.ts` so the response
shape is end-to-end typed:

```ts
import type { paths } from "@/lib/types";
type LineStatus = paths["/api/v1/status/live"]["get"]["responses"]["200"]
  ["content"]["application/json"][number];
```

## Regenerating types from the OpenAPI contract

```bash
make openapi-ts   # runs openapi-typescript ../contracts/openapi.yaml -o lib/types.ts
```

Re-run any time `contracts/openapi.yaml` changes. CI runs the same
generation and `diff`s against the committed file — drift fails the build.

## Security headers

`next.config.ts` registers the project-wide headers required by `CLAUDE.md`:

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

## Tests

68 specs across SSE parser, fetchers, dashboard cards, ChatView, and the
`/` integration test. `vitest.setup.ts` patches jsdom with an in-memory
`localStorage` / `sessionStorage` (Node 25 ships a native `localStorage`
that requires `--localstorage-file`) and stubs `window.matchMedia` for
vaul (drawer primitive).

## Status

Feature-complete:

- TM-E1a: scaffold, security headers, shadcn primitives, Vitest suite.
- TM-E1b: live status fetcher wired to `/api/v1/status/live`.
- TM-E2: disruption view (folded into TM-E5).
- TM-E3: ChatView with SSE.
- TM-E5: one-pager — four dashboard cards + sticky chat panel + drawer fallback.
- TM-E4 (next): Vercel deploy, `NEXT_PUBLIC_API_URL` pointing at the prod API.
