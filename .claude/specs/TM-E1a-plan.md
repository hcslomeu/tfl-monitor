# TM-E1a — Plan

Phase 2 plan for the scaffold-only slice of TM-E1. Source of truth:
`.claude/specs/TM-E1a-research.md`.

## Goal

Land a merged-ready PR that:

1. Adds Vitest (with React Testing Library) to `web/` and writes the
   first frontend tests.
2. Replaces the placeholder Network Now page with a server-rendered
   view that reads from a **mocked** `/status/live` fetcher.
3. Documents the real-API wiring as a TODO for TM-E1b.
4. Leaves `pnpm --dir web {lint,test,build}` and `make check` green.

## What we are NOT doing

- Real wiring to the FastAPI `/api/v1/status/live` endpoint — deferred
  to TM-E1b once TM-D2 ships.
- Disruption Log (`/disruptions`), Reliability (`/reliability`), Ask
  (`/ask`) — those remain untouched stubs (TM-E2 / TM-E3).
- claude.design import for richer UI — deferred (the WP brief allows a
  pragmatic shadcn-only render).
- Re-scaffolding via `pnpm create next-app`. TM-000 already produced
  the canonical layout (Next 16, App Router, no `src/`, `@/*` → `./*`,
  Tailwind 4, Biome). See research §"Tooling decisions" for the
  divergence note.
- Adding charts, maps, or anything that requires a third-party design
  system. Lean by default.
- Wiring `pnpm --dir web test` into CI — that PR-level wiring is
  optional and can ride along with TM-E1b. Local `make check` will
  cover it.

## Internal sub-phases

### Sub-phase 1 — Vitest install + config

**Files**
- `web/package.json` (devDependencies + scripts)
- `web/vitest.config.ts` (new)
- `web/vitest.setup.ts` (new)
- `web/tsconfig.json` (add Vitest globals if needed; keep noEmit)

**Steps**
1. `pnpm --dir web add -D vitest @vitejs/plugin-react jsdom \
   @testing-library/react @testing-library/jest-dom \
   @testing-library/dom`
2. Write `vitest.config.ts`:
   - `import { defineConfig } from "vitest/config"`
   - `react()` plugin
   - `test.environment = "jsdom"`
   - `test.setupFiles = ["./vitest.setup.ts"]`
   - `test.globals = true` (so tests can use `describe`/`it`/`expect`
     without imports — matches Jest ergonomics)
   - `resolve.alias = { "@": path.resolve(__dirname, ".") }`
3. Write `vitest.setup.ts`:
   - `import "@testing-library/jest-dom/vitest"`
4. Update `package.json` scripts:
   - `"test": "vitest run"`
   - `"test:watch": "vitest"`
5. Add `"types": ["vitest/globals", "@testing-library/jest-dom"]` to
   `tsconfig.json` `compilerOptions` so editors and `tsc` see the
   matchers and globals.

**Success criteria**
- `pnpm --dir web test` exits 0 with "no test files" or with the
  smoke tests once they are added in sub-phase 4.
- `pnpm --dir web lint` still green (Biome may complain about unused
  imports — fix as part of this sub-phase).

### Sub-phase 2 — Mocked `/status/live` fetcher

**File**
- `web/lib/api/status-live.ts` (new)

**Steps**
1. Re-export `LineStatus = components["schemas"]["LineStatus"]` from
   `lib/types.ts` for ergonomic imports.
2. Implement `getStatusLive(): Promise<LineStatus[]>`:
   - Static `import mock from "@/lib/mocks/status-live.json"`.
   - Cast through `unknown` to `LineStatus[]` (JSON-typed → schema-typed).
   - Return `Promise.resolve(mock as unknown as LineStatus[])`.
3. Inline comment block:

   ```ts
   // Mock origin: web/lib/mocks/status-live.json (committed fixture
   // mirroring contracts/openapi.yaml LineStatus example).
   //
   // TODO(TM-E1b): replace this body with
   //   return apiFetch<LineStatus[]>("/api/v1/status/live");
   // once TM-D2 wires the FastAPI endpoint to Postgres. The function
   // signature is the contract — call sites do not change.
   ```
4. No new dep, no fetcher abstraction, no factory.

**Success criteria**
- Importable as `import { getStatusLive, type LineStatus } from
  "@/lib/api/status-live"`.
- `pnpm --dir web build` still green (catches type drift).

### Sub-phase 3 — Network Now view

**Files**
- `web/app/page.tsx` (replace body)
- `web/components/status-badge.tsx` (new)

**Steps**
1. `status-badge.tsx`: small client-free component mapping
   `status_severity` to one of three tones using shadcn `Badge`:
   - `severity === 10` → `variant="default"` + green tint
   - `severity ∈ [7, 9]` → `variant="secondary"` + amber tint
   - `severity ≤ 6` → `variant="destructive"` (red, native)
   Use Tailwind utility classes; no extra theme tokens.
2. `app/page.tsx`: convert to an async server component:
   - `const lines = await getStatusLive();`
   - Render a header (`Network Now`, last-updated timestamp from the
     latest `valid_from`).
   - Render an explicit "Mock data — real `/status/live` wiring lands
     in TM-E1b after TM-D2" banner using shadcn `Alert`.
   - Render a list of `Card`s, each row containing:
     - Line name + mode chip
     - `StatusBadge` + severity description
     - Reason (if any) + window (`valid_from` → `valid_to` formatted
       with `Intl.DateTimeFormat("en-GB", { timeStyle: "short" })`).
3. Top of file comment: "Mock data wired via `getStatusLive()`; see
   TM-E1a research/plan."

**Success criteria**
- `pnpm --dir web build` prerenders `/` as static (it stays a server
  component reading committed JSON).
- Visiting `http://localhost:3000` (manual) shows three cards with the
  expected badges.

### Sub-phase 4 — Tests

**Files**
- `web/lib/api/status-live.test.ts` (new)
- `web/app/__tests__/network-now.test.tsx` (new)

**Steps**
1. `status-live.test.ts`:
   - Imports `getStatusLive` and the mock JSON.
   - Asserts: returns ≥ 1 entry, every entry has all required
     `LineStatus` fields, severity is in `[0, 20]`.
2. `network-now.test.tsx`:
   - Renders the server component as React (`await Page()` returns a
     React element; pass it directly to RTL `render`).
   - Asserts the page contains the words "Network Now", "Victoria",
     "Piccadilly", "Elizabeth", and the mock-data banner copy.

**Success criteria**
- `pnpm --dir web test` exits 0 with at least 2 test files / 4
  assertions.
- `pnpm --dir web lint` still green.

### Sub-phase 5 — README + PROGRESS + Makefile + current-wp

**Files**
- `web/README.md`
- `README.md` (root)
- `PROGRESS.md`
- `Makefile`
- `.claude/current-wp.md` (only after PR opens)

**Steps**
1. `web/README.md`: document the new `pnpm --dir web {dev,build,lint,
   test}` flow and the `make openapi-ts` type-regen tip. Mention the
   mock-vs-real switch deferred to TM-E1b.
2. Root `README.md`:
   - Update the tech-stack row from "Next.js 15" to "Next.js 16".
   - Append a note in the Local development block calling out
     `pnpm --dir web test` for the new Vitest suite.
3. `PROGRESS.md`: split TM-E1 into TM-E1a / TM-E1b inline, marking
   TM-E1a as ✅ today with the note "scaffold + mocked data; real
   wiring in E1b post-D2".
4. `Makefile`: extend the `check` target to run `pnpm --dir web test`
   between lint and build.
5. `.claude/current-wp.md`: defer until the PR is opened (per the
   author's existing convention of bumping it post-merge).

**Success criteria**
- `make check` runs end-to-end without prompting.
- README is internally consistent (no "Next.js 15" leftovers in the
  pieces I touched).

## Verification gauntlet (pre-PR)

```bash
pnpm --dir web lint
pnpm --dir web test
pnpm --dir web build
make check
```

Manual:
- `pnpm --dir web dev` → http://localhost:3000 shows three line cards
  with severity badges and the mock banner.

## Branch + commit plan

- Branch: `feature/TM-E1a-nextjs-scaffold`
- One commit (or two if the diff is large): the WP is contained.

Suggested commit subject:

```
feat(web): TM-E1a Vitest + Network Now mocked view (TM-11)
```

PR title:

```
feat(web): TM-E1a Next.js scaffold + shadcn + Network Now (mocked) (TM-11)
```

PR body must explicitly state real-API wiring is deferred to TM-E1b.
