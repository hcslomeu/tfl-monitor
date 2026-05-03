# web/

Next.js 16 dashboard for tfl-monitor — three views (Network Now, Disruption
Log, Ask), all server components by default, types regenerated from the
OpenAPI contract.

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
├─ app/                      # App Router routes
│  ├─ page.tsx               # Network Now (/)
│  ├─ disruptions/page.tsx   # Disruption Log
│  └─ ask/page.tsx           # ChatView host
├─ components/
│  ├─ chat-view.tsx          # SSE-streaming chat
│  └─ ui/                    # shadcn primitives
├─ lib/
│  ├─ api/                   # Server-side fetchers
│  ├─ sse-parser.ts          # 60-line stateful SSE parser
│  └─ types.ts               # generated — do not edit
├─ __tests__/                # Vitest specs
├─ next.config.ts            # Security headers
└─ biome.json                # Single config for lint + format
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

## Views and wiring

| Route | Endpoint | Highlights |
|-------|----------|------------|
| `/` | `/api/v1/status/live` | Empty / error states via `Alert role="alert"`; fetcher catches `ApiError` |
| `/disruptions` | `/api/v1/disruptions/recent` | Per-disruption Card, category-tone badge, closure callout |
| `/ask` | `/api/v1/chat/stream` (POST SSE) | Token bubbles, ephemeral "Using tool …" status, mid-stream error flag |

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

54 specs across:

- **SSE parser** — single frame, multi-frame chunk, partial chunk buffering,
  ping comments, unknown-type drop, malformed-JSON survival.
- **Fetchers** — URL/headers/body assertions, RFC 7807 surfacing, network
  failure propagation, multi-chunk reader buffering.
- **Pages** — happy path, empty state, error state, RTL queries scoped via
  `findByRole("alert")` to disambiguate title/description.
- **ChatView** — empty shell, streaming tokens, tool-status lifecycle,
  503 alert + conversation rollback, mid-stream `end:error` flagging via
  `data-errored`.

`web/__tests__/setup.ts` initialises `jsdom` and stubs `fetch` per test via
`vi.stubGlobal`.

## Status

Feature-complete:

- TM-E1a: scaffold, security headers, shadcn primitives, Vitest suite.
- TM-E1b: Network Now wired to live `/status/live`.
- TM-E2: Disruption Log view.
- TM-E3: Chat view with SSE.
- TM-E4 (next): Vercel deploy, `NEXT_PUBLIC_API_URL` pointing at the EC2
  HTTPS endpoint.
