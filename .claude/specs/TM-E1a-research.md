# TM-E1a — Research

Phase 1 (read-only) findings for TM-E1a: scaffold-only slice of TM-E1.

## Mission recap

- Next.js 16 app under `web/` with TypeScript, App Router, Biome, Vitest
  and shadcn/ui (Radix Nova preset).
- Render a Network Now page from a **mocked** `/status/live` payload.
- Real-API wiring is deferred to TM-E1b after TM-D2 lands.
- Hard rules: pnpm only, English-on-disk, one linter (Biome), one test
  runner (Vitest), security headers required, no Co-Authored-By.

## Repository state at branch `main`

The `web/` folder was already scaffolded as part of TM-000. The concrete
shape:

| Concern | Already in place | Source |
|---|---|---|
| Next.js scaffold | `web/` with `next@16.2.4`, React 19, App Router, Tailwind 4, `@/*` alias mapped to `./*` (no `src/` dir) | `web/package.json`, `web/tsconfig.json` |
| Biome | `biome.json` at `web/` root, tabs, double quotes, recommended rules, `lib/types.ts` ignored, `vcs.useIgnoreFile=true` | `web/biome.json` |
| shadcn/ui | `components.json` with `style: "radix-nova"`, `baseColor: "neutral"`, `iconLibrary: "lucide"`. Six primitives generated: `alert`, `badge`, `button`, `card`, `skeleton`, `tabs` | `web/components.json`, `web/components/ui/` |
| OpenAPI → TS | `openapi-typescript@7.13.0` dev dep, `make openapi-ts` regenerates `web/lib/types.ts` from `contracts/openapi.yaml`; current `lib/types.ts` matches the contract | `web/lib/types.ts`, root `Makefile` |
| Mock fixtures | `web/lib/mocks/{status-live,disruptions-recent,reliability}.json` with realistic shapes mirroring the OpenAPI examples | `web/lib/mocks/` |
| Generic fetcher | `web/lib/api-client.ts` with `apiFetch<T>`, `ApiError`, `NEXT_PUBLIC_API_URL` fallback to `http://localhost:8000` | `web/lib/api-client.ts` |
| Pages | App Router routes: `/` (placeholder Network Now card), `/disruptions`, `/reliability`, `/ask` — all currently render scaffolded cards | `web/app/*` |
| Security headers | `next.config.ts` registers `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, plus a `Permissions-Policy` add-on | `web/next.config.ts` |
| `pnpm --dir web lint` | ✅ passes (`Checked 23 files in 70ms`) | local run |
| `pnpm --dir web build` | ✅ passes (`Next.js 16.2.4 (Turbopack)`, prerenders `/`, `/ask`, `/disruptions`, `/reliability`) | local run |
| `pnpm --dir web test` | ⚠️ stub (`echo 'No frontend tests yet — Vitest suite lands with TM-E1' && exit 0`) | `web/package.json` |
| `pnpm-workspace.yaml` | present (lists `ignoredBuiltDependencies`) | `web/pnpm-workspace.yaml` |
| Root `Makefile` `check` | already chains `pnpm --dir web lint` and `pnpm --dir web build`; does **not** yet run `pnpm --dir web test` | root `Makefile` |
| Linter situation | Only Biome configured. There is no ESLint/Prettier config in `web/` to remove. | grep |

### `/status/live` contract

`contracts/openapi.yaml` defines `LineStatus` as an array of:

```yaml
required: [line_id, line_name, mode, status_severity,
           status_severity_description, valid_from, valid_to]
mode: enum [tube, elizabeth-line, overground, dlr, bus,
            national-rail, river-bus, cable-car, tram]
status_severity: integer 0..20
reason: string | null
valid_from / valid_to: ISO date-time
```

The generated `web/lib/types.ts` exposes
`components["schemas"]["LineStatus"]` so we can re-use the generated
type instead of hand-typing it. `paths["/api/v1/status/live"]` is also
present.

The mock JSON `web/lib/mocks/status-live.json` already contains three
representative rows (Victoria, Piccadilly, Elizabeth) at severities 10,
6, 9 — enough variation to render colour-coded badges in the Network
Now view.

## Gap analysis — what TM-E1a still has to deliver

1. **Vitest + smoke test.** No test runner installed, no `vitest.config.ts`,
   no test file. Need:
   - `vitest`, `@vitejs/plugin-react`, `@testing-library/react`,
     `@testing-library/jest-dom`, `jsdom`, `@types/node` (already
     present), and a `vitest.setup.ts` registering jest-dom matchers.
   - `vitest.config.ts` with the React plugin, `environment: "jsdom"`,
     `setupFiles`, and the `@/*` alias.
   - One smoke test for `lib/api/status-live.ts` and one component
     test for the Network Now page rendering mocked rows.
2. **Mock fetcher module.** Mission requires `web/lib/api/status-live.ts`.
   Today the mock JSON exists in `lib/mocks/` but no fetcher imports it.
   Module shape:
   - `getStatusLive(): Promise<LineStatus[]>` returning the mocked JSON
     after a short async tick.
   - Inline TODO comment: switch to `apiFetch<LineStatus[]>("/api/v1/status/live")`
     once TM-D2 ships.
   - Re-export `LineStatus` type from `lib/types.ts`.
3. **Network Now view.** `app/page.tsx` is a placeholder. Replace with
   an async server component that calls `getStatusLive()` and renders
   each line as a card row with a status badge whose tone derives from
   `status_severity` (10 → good, 7–9 → minor, ≤6 → severe). Add a
   visible "Mock data — real wiring lands in TM-E1b" banner so the
   demo is honest.
4. **`package.json` test script.** Replace the echo stub with
   `vitest run`. Add `test:watch` for local DX. Update Makefile `check`
   target to include `pnpm --dir web test`.
5. **README.** Root `README.md` mentions the `web/` quickstart in the
   "Local development" block but pre-dates Vitest. Add an explicit
   `### web/ — frontend` subsection covering `pnpm --dir web {dev,
   build, lint, test}` plus the `make openapi-ts` regeneration tip.
   Also flip the README tech-stack row from "Next.js 15" to "Next.js
   16" (already updated in `CLAUDE.md` and `ARCHITECTURE.md`).
6. **PROGRESS.md.** Add inline note for TM-E1a:
   "scaffold + mocked data; real wiring in E1b post-D2".

## Tooling decisions

- **Re-scaffold? No.** TM-000 already produced the canonical Next.js
  16 + Biome + Tailwind 4 + shadcn radix-nova layout. Re-running
  `pnpm create next-app@latest web --src-dir …` would destroy committed
  work and would not match what TM-000 shipped (the spec already
  captured a deviation: scaffold uses no `src/` dir, alias `@/*` →
  `./*`). Mission text "create `web/` via pnpm create next-app" is
  satisfied in spirit by the existing layout — flagging this divergence
  here per CLAUDE.md "report when reality diverges from the plan".
- **Type generation.** Re-use the existing
  `components["schemas"]["LineStatus"]` from `lib/types.ts`. Hand-typing
  would drift from the contract; the generated file is already wired
  through `make openapi-ts`.
- **Vitest version.** Use `vitest@^2` (current LTS; works with React 19
  and Tailwind 4 via `@vitejs/plugin-react`). `jsdom` rather than
  `happy-dom` because it has fewer compatibility surprises with React
  19's experimental APIs.
- **Mock origin.** Keep the JSON file under `lib/mocks/status-live.json`
  (already committed). The fetcher imports it via static `import` —
  Vitest resolves JSON natively and Next.js bundles it into the server
  component.

## Risks / open questions

- None blocking. Next.js 16 + Vitest 2 + jsdom is a known-good combo;
  `@testing-library/react@16` supports React 19.
- Tailwind 4 PostCSS pipeline is unaffected by Vitest because Vitest
  runs against TSX directly without Tailwind processing in unit tests
  (we assert on classnames as strings, not on rendered styles).

## Files this WP will touch

```
web/package.json                          (add vitest + RTL deps, scripts)
web/vitest.config.ts                      (new)
web/vitest.setup.ts                       (new)
web/lib/api/status-live.ts                (new)
web/lib/api/status-live.test.ts           (new)
web/app/page.tsx                          (replace placeholder)
web/app/__tests__/network-now.test.tsx    (new)
web/components/status-badge.tsx           (new — small helper)
web/README.md                             (expand)
README.md                                 (root quickstart + tech-stack note)
PROGRESS.md                               (TM-E1a row note)
Makefile                                  (chain `pnpm --dir web test`)
.claude/current-wp.md                     (point at TM-E1b once PR opens)
```

No backend changes. Contracts untouched. Python toolchain untouched.
