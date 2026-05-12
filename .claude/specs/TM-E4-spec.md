# TM-E4 — Frontend migration to claude.design system + Vercel deploy

Status: draft (awaiting Phase 3 go-ahead)
Started: 2026-05-12
Spec author: Claude Code
Linear issue: TM-E4

## 1. Goal

Replace the existing Tailwind + shadcn dashboard with the bespoke
"Humberto Lomeu Design System" surface designed in claude.design, then
ship the result to Vercel as a public portfolio frontend.

Demo data fixtures ship by default so the frontend is fully usable
without a production backend (TM-A3 / TM-A5 still pending).

## 2. Locked decisions

| Decision | Value |
|---|---|
| CSS stack | Vanilla CSS only — drop Tailwind, shadcn, tw-animate, radix-ui, vaul |
| Design system location | `web/styles/design-system/{tokens.css, tfl-monitor.css}` |
| Fonts | Self-hosted in `web/public/fonts/` (PP Editorial New); Inter/JetBrains Mono/Geist via `next/font/google` |
| Logos / assets | `web/public/` (e.g. `tfl-monitor-logo.svg`) |
| Mock data | `NEXT_PUBLIC_USE_MOCKS` env flag, default `true`; fixtures hardcoded to match the design canvas (Elizabeth severe, Northern part-suspended, Waterloo & City suspended) |
| Naming | Drop `TFL` prefix. `TFLLineGrid` → `LineGrid`, `TFLChat` → `ChatPanel`, `TFLNav` → `TopNav`, etc. |
| Tests | Delete existing dashboard tests. Add minimal smoke tests per new component + a single page-level integration test. |
| Component dir | `web/components/dashboard/` (reuse existing path) |

## 3. Source inventory

### 3.1 Design system inputs

Path: `/Users/humbertolomeu/tfl-monitor/Humberto Lomeu Design System/`

| File | Lines | Role |
|---|---|---|
| `colors_and_type.css` | 366 | Shared tokens (palette, type, spacing, radii, shadows, motion) + base element styles. Imports Inter/JetBrains/Geist from Google Fonts, declares 6 `@font-face` for PP Editorial New. |
| `ui_kits/tfl_monitor/tfl_monitor.css` | 284 | Product-surface CSS: `.tfl-nav`, `.tfl-grid`, `.tfl-card`, `.tfl-line*`, `.tfl-detail*`, `.tfl-disruption`, `.tfl-stations`, `.tfl-bus*`, `.tfl-news*`, `.tfl-chat*`. Dense product density. |
| `ui_kits/tfl_monitor/Components.jsx` | 246 | Seven vanilla React components (`TFLNav`, `TFLPageHead`, `TFLLineGrid`, `TFLLineDetail`, `TFLBusBanner`, `TFLNewsReports`, `TFLChat`) + static `LINES`, `TFL_NEWS` mock data. |
| `ui_kits/tfl_monitor/index.html` | 41 | Preview shell — defines the App layout: `TopNav` over a 2-col grid (left: `LineGrid` + `BusBanner` + `NewsReports`; right: `LineDetail` + `ChatPanel`). |
| `assets/tfl-monitor-logo.svg` | — | Brand logo. |
| `fonts/PPEditorialNew-*.otf` × 6 | — | Self-hosted PP Editorial New weights/styles (Ultralight, Regular, Ultrabold + italics). |

### 3.2 Existing web/ state (to be partially demolished)

Keep:
- `web/lib/api/{status-live.ts, disruptions-recent.ts, chat-stream.ts}` (+ tests)
- `web/lib/api-client.ts` (ApiError class)
- `web/lib/hooks/use-auto-refresh.ts`
- `web/lib/types.ts`
- `web/lib/labels.ts` (status bucket mapping)
- `web/lib/utils.ts` (only if non-cn helpers; `cn` is Tailwind-specific, delete that helper)
- `web/lib/mocks/*` (extend with new fixtures)
- `web/lib/sse-parser.ts` (+ tests)
- `web/vitest.{config,setup}.ts`
- `web/biome.json`
- `web/tsconfig.json`
- `web/next.config.ts`
- `web/pnpm-*`, `web/package.json` (edit deps)
- `web/README.md` (rewrite section about visual stack)

Delete:
- `web/components/dashboard/{chat-panel,coming-up-card,happening-now-card,network-pulse-tile,network-status-card}.tsx` (+ `__tests__`)
- `web/components/{about-sheet, chat-view, status-badge}.tsx`
- `web/components/ui/*` (shadcn primitives)
- `web/components.json` (shadcn registry config)
- `web/app/__tests__/page.test.tsx` (rewrite for new layout)
- Tailwind/shadcn deps from `package.json`
- Tailwind/shadcn imports from `web/app/globals.css`

## 4. Final architecture

```
web/
├─ app/
│  ├─ globals.css            # imports design-system tokens + product CSS only
│  ├─ layout.tsx             # next/font loaders, body className="density-product"
│  ├─ page.tsx               # App shell: TopNav + 2-col grid composition
│  └─ __tests__/page.test.tsx
├─ components/
│  └─ dashboard/
│     ├─ top-nav.tsx          (← TFLNav)
│     ├─ page-head.tsx        (← TFLPageHead)
│     ├─ line-grid.tsx        (← TFLLineGrid)
│     ├─ line-detail.tsx      (← TFLLineDetail)
│     ├─ bus-banner.tsx       (← TFLBusBanner)
│     ├─ news-reports.tsx     (← TFLNewsReports)
│     ├─ chat-panel.tsx       (← TFLChat)
│     ├─ icons.tsx            (TFLIcon + path constants)
│     └─ __tests__/*.test.tsx
├─ lib/
│  ├─ api/                   # untouched
│  ├─ api-client.ts          # untouched
│  ├─ hooks/use-auto-refresh.ts
│  ├─ types.ts
│  ├─ labels.ts
│  ├─ mocks/
│  │  ├─ lines.ts            # 14 lines matching design canvas
│  │  ├─ disruptions.ts      # Elizabeth severe etc
│  │  ├─ buses.ts            # 4 routes
│  │  ├─ news.ts             # 3 entries
│  │  └─ index.ts            # USE_MOCKS guard
│  └─ env.ts                 # NEXT_PUBLIC_USE_MOCKS resolver
├─ public/
│  ├─ fonts/
│  │  └─ PPEditorialNew-{Ultralight,UltralightItalic,Regular,Italic,Ultrabold,UltraboldItalic}.otf
│  └─ tfl-monitor-logo.svg
└─ styles/
   └─ design-system/
      ├─ tokens.css           (← colors_and_type.css, font paths rewritten to /fonts/)
      └─ tfl-monitor.css      (← ui_kits/tfl_monitor/tfl_monitor.css, unchanged)
```

### 4.1 Layout composition (new `app/page.tsx`)

```
<TopNav summary={summary} clock={now} />
<main className="tfl-grid">
  <PageHead lastRefreshed={...} />          (full-width row)
  <div className="tfl-left-col">
    <LineGrid lines={lines} selected={code} onSelect={setCode} />
    <BusBanner buses={buses} />
    <NewsReports items={news} />
  </div>
  <div className="tfl-right-col">
    <LineDetail line={selectedLine} disruption={selectedDisruption} />
    <ChatPanel />
  </div>
</main>
```

### 4.2 Data flow

- `NEXT_PUBLIC_USE_MOCKS=true` (default) → `lib/mocks/*` exports static fixtures, page-level fetch wrappers short-circuit and return fixtures synchronously.
- `NEXT_PUBLIC_USE_MOCKS=false` + `NEXT_PUBLIC_API_BASE_URL=...` → real fetches via existing `api-client`. Loading + error states fall through to skeleton placeholders in components.

### 4.3 Fonts

`web/app/layout.tsx`:
```ts
import localFont from "next/font/local";
import { Inter, JetBrains_Mono, Geist } from "next/font/google";

const editorial = localFont({
  src: [
    { path: "../public/fonts/PPEditorialNew-Ultralight.otf", weight: "200", style: "normal" },
    { path: "../public/fonts/PPEditorialNew-UltralightItalic.otf", weight: "200", style: "italic" },
    { path: "../public/fonts/PPEditorialNew-Regular.otf", weight: "400", style: "normal" },
    { path: "../public/fonts/PPEditorialNew-Italic.otf", weight: "400", style: "italic" },
    { path: "../public/fonts/PPEditorialNew-Ultrabold.otf", weight: "800", style: "normal" },
    { path: "../public/fonts/PPEditorialNew-UltraboldItalic.otf", weight: "800", style: "italic" },
  ],
  variable: "--font-display-local",
  display: "swap",
});
```

`globals.css` token override:
```css
:root { --font-display: var(--font-display-local), 'Fraunces', serif; }
```

This avoids the `@font-face` in `tokens.css` (drop those 6 blocks; the Google Fonts `@import` for Inter/JetBrains/Geist also drops in favour of `next/font/google` injected variables).

### 4.4 Vercel deploy config

- `web/` already self-contained — set Vercel **Root Directory** = `web`.
- Framework preset: **Next.js** (auto-detected).
- Install: `pnpm install --frozen-lockfile` (auto).
- Build: `pnpm build`.
- Env:
  - `NEXT_PUBLIC_USE_MOCKS=true` (preview + production until backend prod exists).
  - `NEXT_PUBLIC_API_BASE_URL` unset for now.
- Domain: `tfl-monitor.humbertolomeu.com` (per design system README) — assign after first successful deploy.
- Security headers (per CLAUDE.md): add to `next.config.ts` under `headers()`:
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`

## 5. Migration phases

### Phase 1 — Token + asset bootstrap

1. Create `web/styles/design-system/{tokens.css, tfl-monitor.css}`. Copy upstream sources verbatim; in `tokens.css` rewrite the 6 `url('fonts/…otf')` references to `url('/fonts/…otf')` and drop the Google Fonts `@import` (next/font handles those).
2. Copy 6 `PPEditorialNew-*.otf` → `web/public/fonts/`.
3. Copy `tfl-monitor-logo.svg` → `web/public/`.
4. Rewrite `web/app/globals.css` to a 3-line file: imports of tokens + tfl-monitor stylesheets, plus the `:root` font-variable override.
5. Update `web/app/layout.tsx`: register 4 fonts (3 google + 1 local), set body class to `density-product` plus the CSS variable wiring.
6. Verify `pnpm build` succeeds even with old components still present.

### Phase 2 — Strip Tailwind + shadcn

1. Delete `web/components/ui/*`, `web/components/{about-sheet, chat-view, status-badge}.tsx`, `web/components/dashboard/*`, `web/components.json`.
2. Delete `web/app/__tests__/page.test.tsx`.
3. Edit `package.json` — remove: `tailwindcss`, `@tailwindcss/postcss`, `tw-animate-css`, `radix-ui`, `vaul`, `class-variance-authority`, `tailwind-merge`, `shadcn` (dev), `clsx` (optional — keep if used elsewhere).
4. Delete `web/postcss.config.mjs` (if no other PostCSS plugins).
5. Run `pnpm install` to refresh lockfile.
6. Verify `pnpm build` + `pnpm lint` (Biome) pass.

### Phase 3 — Port components

For each of the 7 source components in `ui_kits/tfl_monitor/Components.jsx`:

1. Create `web/components/dashboard/<kebab>.tsx`.
2. Convert vanilla JSX → typed React 19 client component.
3. Replace static fixtures with props.
4. Move `TFLIcon` + path constants to `components/dashboard/icons.tsx`.
5. Drop `TFL` prefix from exported names.
6. Keep CSS class names exactly as written (`tfl-card`, `tfl-line` etc.) so styles match without edits.

Smoke test per component (`__tests__/<name>.test.tsx`): mount with minimal props, assert key strings render.

### Phase 4 — Mocks + env

1. Create `web/lib/mocks/{lines,disruptions,buses,news}.ts` with the data from `Components.jsx`'s static arrays.
2. Create `web/lib/env.ts` with `export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS !== "false"` (default-on).
3. Wrap existing `getStatusLive` / `getRecentDisruptions` so they short-circuit to fixtures when `USE_MOCKS`. The fetch path remains intact for when the backend is live.

### Phase 5 — Page rewrite

1. Rewrite `web/app/page.tsx` to compose `TopNav` + grid as in §4.1.
2. Wire `useAutoRefresh` to the wrapped fetchers (mocks ignore the abort signal, fixtures arrive synchronously).
3. Add `web/app/__tests__/page.test.tsx`: render page with mocks ON, assert nav summary, line grid header, line detail header all present.

### Phase 6 — Verification + deploy

1. `pnpm lint && pnpm test && pnpm build` — must pass.
2. `pnpm dev` — manual smoke in browser at `http://localhost:3000`: hover/click each line, send a chat message, verify dark composer, verify mobile breakpoint at 880px.
3. `vercel link` if not yet linked → `vercel deploy` preview.
4. Inspect preview URL: same manual smoke list.
5. `vercel deploy --prod` once preview looks correct.
6. Add custom domain `tfl-monitor.humbertolomeu.com`.

## 6. Acceptance criteria

Automated:
- `make check` passes (Python side untouched; TS side: `pnpm --dir web lint && pnpm --dir web test`).
- `pnpm --dir web build` produces a successful prod build.
- Zero Tailwind / shadcn references in `web/` after Phase 2 (`grep -r "tailwind\|shadcn\|tw-animate" web/src web/app web/components web/lib` returns empty).

Manual:
- Browser at `http://localhost:3000` renders the design canvas pixel-faithfully against `Humberto Lomeu Design System/ui_kits/tfl_monitor/index.html` opened side-by-side.
- Selecting a line in `LineGrid` updates `LineDetail` (state lifted to the page).
- Sending a chat message appends to the transcript and clears the input.
- Mobile breakpoint at 880px collapses to single column.
- Vercel preview deploy resolves at the assigned preview URL.

## 7. What we're NOT doing

- No backend deploy (TM-A3 Supabase, TM-A5 AWS remain pending).
- No real SSE wiring for the chat — `ChatPanel` is local-state only until backend is live.
- No dark mode (design system locks light-first; product surfaces may add dark later — out of scope).
- No accessibility audit pass — focus-visible + keyboard nav work, but no formal WCAG sweep.
- No service worker / PWA.
- No internationalisation.
- No replacement for Drawer/Dialog primitives — if a modal is needed later, Radix is re-added as an isolated dep.
- No removal of Python backend code, dbt, Airflow — frontend-only work.

## 8. Open questions

None remaining. All locked in §2.

## 9. Risk + rollback

- Risk: Geist / Inter loaded via next/font/google + design system also referencing Geist via Google Fonts `@import` (now removed) → confirm no double-load.
- Risk: dropping `clsx` / `cn` helper may break any utility imported elsewhere — grep before deletion.
- Rollback: this WP lives on a single feature branch. If anything breaks badly, revert the branch and main stays on the previous shadcn build (already production-quality per TM-E5).
