# web/

Next.js 16 dashboard for tfl-monitor — Network Now, Disruption Log,
Reliability, and the conversational Ask view land progressively across
TM-E1 → TM-E3.

## Stack

- Next.js 16 App Router on React 19
- Tailwind CSS 4 (PostCSS pipeline)
- shadcn/ui — Radix Nova preset
- Biome (sole linter + formatter; no ESLint, no Prettier)
- Vitest + React Testing Library (sole test runner)
- TypeScript types regenerated from `contracts/openapi.yaml` via
  `make openapi-ts` (writes `web/lib/types.ts`)

## Quickstart

```bash
pnpm --dir web install   # only needed if you skipped `make bootstrap`
pnpm --dir web dev       # dev server on :3000
pnpm --dir web lint      # Biome check
pnpm --dir web test      # Vitest run
pnpm --dir web build     # Next production build
```

`make check` at the repo root chains lint + test + build for both
Python and TypeScript.

## Status

- TM-E1a (this WP) ships the scaffold, security headers, shadcn
  primitives, the Vitest suite, and a Network Now view that renders
  **mocked** `/status/live` data committed under
  `web/lib/mocks/status-live.json`.
- Real-API wiring is deferred to TM-E1b: swap the body of
  `web/lib/api/status-live.ts` for `apiFetch<LineStatus[]>(...)` once
  TM-D2 connects the FastAPI handler to Postgres. The fetcher
  signature is the contract — call sites do not change.

## Regenerating types from the OpenAPI contract

```bash
make openapi-ts
```

This runs `openapi-typescript ../contracts/openapi.yaml -o lib/types.ts`
inside `web/`. Re-run any time `contracts/openapi.yaml` changes.

## Security headers

`next.config.ts` registers the project-wide headers required by
`CLAUDE.md`:

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
