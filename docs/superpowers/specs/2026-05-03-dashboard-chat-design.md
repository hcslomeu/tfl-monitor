# 2026-05-03 — Dashboard + chat one-pager design

**Status:** design (brainstormed)
**Probable WP:** TM-E5 (E-frontend track)
**Author:** Humberto Lomeu (with Claude Opus 4.7)
**Predecessors:** TM-E1b (Network Now wired), TM-E2 (Disruption Log), TM-E3 (Chat with SSE), TM-D5 (LangGraph agent)
**Successor:** implementation plan (writing-plans skill — next)

---

## 1. Charter

Collapse the existing four-route TfL frontend (`/`, `/disruptions`, `/reliability`, `/ask`) into a **single one-pager** that serves a London commuter / recruiter both useful real-time TfL information and a strategy-aware chat agent in one screen.

### Success criteria

| # | Criterion | Verification |
|---|---|---|
| 1 | A first-time visitor on a 13″ MacBook (1440×900) sees, in under 2 seconds and without scrolling: live tube line statuses, today's incidents, upcoming planned works, and a working chat box. | Manual demo on a 13″ MacBook |
| 2 | Real-time data refreshes without page reload: line status every 30 s, disruptions every 5 min. | Network tab observation + integration test stub |
| 3 | Mode tabs (Tube / Elizabeth / Overground / DLR / Tram·River·Cable / Bus) switch the *Network status* card without unmounting the rest of the page. | Vitest + manual click |
| 4 | The chat panel works on the same page while a user reads disruption cards (no view swap). | Manual session |
| 5 | All four legacy routes (`/disruptions`, `/reliability`, `/ask`, plus the original `/` Network-only landing) are gone or redirect to `/`. | `next build` route table |
| 6 | Below 1024 px the page stacks (cards on top, chat as bottom-sheet drawer). | Manual via dev-tools responsive mode |

---

## 2. Locked decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Single-page architecture** — only `/` lives. | User explicitly rejected tab-navigation and separate routes; portfolio recruiter must see breadth without clicks. |
| D2 | **2/3 + 1/3 horizontal split at `lg` (≥ 1024 px)** — dashboard left, chat right, both visible simultaneously. | 13″ MBP renders 1440 × 900 → 960 px dashboard / 480 px chat → comfortable both sides. |
| D3 | **Mode tabs inside the *Network status* card** — Tube default, sticky last-tab in `localStorage`. | Tube has the highest line variety (11 lines) and recruiter recognition; default lands the strongest first impression. |
| D4 | **Disruption category split into two cards** — *Happening now* (`category=RealTime` ∪ `Incident`) and *Coming up* (`category=PlannedWork`, sorted by `created` ASC). | The existing `/disruptions/recent` payload already carries `category`; no new endpoint, no new column. |
| D5 | **Network pulse tile** as the bottom strip — derived metric "X of Y Tube lines · Good service" + traffic-light tally + cross-mode total. | Replaces the cut reliability strip; computed client-side from `/status/live`, zero new endpoint. |
| D6 | **Reliability card cut from the dashboard.** Mart and `/reliability/{line_id}` endpoint stay; the data is exposed only through the chat tool `query_line_reliability` (already wired in TM-D5). | User judgment: card not useful at-a-glance; preserves the dbt warehouse signal in chat without polluting hero. |
| D7 | **Bus punctuality card cut.** `/bus/{stop_id}/punctuality` stays as a chat tool. | Only 5 NaPTAN hubs are ingested (TM-B4 limit) and the metric is a documented 5-min proxy — too narrow for hero. |
| D8 | **Chat right-pane is the same `<ChatView>` component shipped in TM-E3.** No fork. | Avoids duplicating the SSE parser / fetcher / message state; layout-only re-host via prop overrides for height. |
| D9 | **Chat is *not* yet route-aware.** No "current page context" payload in v1. | Single page = no other context. Stays simple for v1; revisit when routes return (e.g. iOS deep links). |
| D10 | **Auto-refresh cadence matches data freshness.** Live status: `setInterval 30_000`. Disruptions: `setInterval 300_000`. Network pulse: derived synchronously from the live-status state, no separate timer. | Mirrors the producer cadences (`LineStatusProducer` 30 s, `DisruptionsProducer` 300 s). |
| D11 | **Wireframe styling is placeholder.** Final visual polish (TfL brand colours, typography, spacing, dark mode) is deferred. | Author explicitly accepted ugly wireframe; polish is a separate concern post-functional. |
| D12 | **iOS port is parked** in a Linear ticket; today's work is web-only. The native Swift app, if it happens later, will mirror option *C* (chat-first with seeded summary), not this dashboard. | Author decision. |

---

## 3. Architecture

### 3.1 Route topology

```
Before                            After
──────                            ─────
/                Network Now      /          Dashboard + chat (one-pager)
/disruptions     Disruption Log   (deleted)
/reliability     Coming soon      (deleted)
/ask             Chat-only        (deleted; redirect → /)
```

`next.config.ts` adds permanent redirects from `/disruptions`, `/reliability`, `/ask` to `/` so that any link already shared survives.

### 3.2 Component tree

```
app/
  layout.tsx                 (unchanged — root layout, fonts, globals)
  page.tsx                   (rewritten — orchestrates the one-pager)
  __tests__/
    page.test.tsx            (rewritten)

components/
  dashboard/
    network-status-card.tsx     (new — mode tabs + line-status grid)
    happening-now-card.tsx      (new — RealTime + Incident filter)
    coming-up-card.tsx          (new — PlannedWork filter)
    network-pulse-tile.tsx      (new — derived metric strip)
    chat-panel.tsx              (new — wraps <ChatView> with sticky styling)
    auto-refresh.tsx            (new — generic <AutoRefresh interval={ms}> wrapper)
    __tests__/
      network-status-card.test.tsx
      happening-now-card.test.tsx
      coming-up-card.test.tsx
      network-pulse-tile.test.tsx

  chat-view.tsx                  (unchanged — TM-E3 component, reused as-is)
  status-badge.tsx               (unchanged — TM-E1 component)
  ui/                            (unchanged — shadcn primitives)

lib/
  api/
    status-live.ts               (unchanged)
    disruptions-recent.ts        (extended — accept optional category filter on client side; endpoint untouched)
    chat-stream.ts               (unchanged)
  api-client.ts                  (unchanged)
  hooks/
    use-auto-refresh.ts          (new — generic SWR-less polling hook)
```

### 3.3 Layout grid

The page uses a single Tailwind grid:

```jsx
<main className="mx-auto max-w-screen-2xl px-6 py-6">
  <header>{/* logo · GitHub link · about */}</header>

  <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-6">

    {/* 2/3 dashboard (lg+) */}
    <section className="flex flex-col gap-4">
      <NetworkStatusCard />        {/* mode tabs + grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <HappeningNowCard />
        <ComingUpCard />
      </div>
      <NetworkPulseTile />
    </section>

    {/* 1/3 chat (lg+) */}
    <aside className="lg:sticky lg:top-6 lg:h-[calc(100vh-3rem)]">
      <ChatPanel />
    </aside>

  </div>
</main>
```

Below `lg` the `aside` un-sticks and the chat panel renders as a collapsible bottom sheet (Radix `Drawer` + a `FAB` button).

### 3.4 Data flow

```
                         ┌──────────────────────────────┐
                         │   FastAPI (existing)         │
                         │   /api/v1/status/live        │
                         │   /api/v1/disruptions/recent │
                         │   /api/v1/chat/stream (SSE)  │
                         └──────────────┬───────────────┘
                                        │
                                  apiFetch / fetch
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                         ▼                         ▼
       useAutoRefresh           useAutoRefresh              streamChat
       (30 s, status-live)      (300 s, disruptions)        (no polling)
              │                         │                         │
              ▼                         ▼                         ▼
     NetworkStatusCard        HappeningNowCard +              ChatPanel
            +                  ComingUpCard share
     NetworkPulseTile          a single fetch → split
     share a single            client-side by category
     fetch
```

The two SWR-less hooks live above the cards in `app/page.tsx` so each fetch is performed once and the data fans out. The page is a **client component** (`"use client"` at the top); `app/page.tsx` was a server component pre-TM-E5 — the trade-off is a slightly larger client bundle, accepted because real-time refresh is the whole point.

### 3.5 Mode-tab state

`NetworkStatusCard` owns its own `selectedMode` state in `useState`, persisted to `localStorage` (`tfl-monitor:last-mode`) on change. The list of modes is derived from the `LineStatus.mode` enum (`tube`, `elizabeth-line`, `overground`, `dlr`, `bus`, `national-rail`, `river-bus`, `cable-car`, `tram`); the UI groups the long tail (Tram, River, Cable) into one tab labelled "Tram · River · Cable" to keep the bar from wrapping.

### 3.6 Network pulse derivation

`NetworkPulseTile` consumes the same `LineStatus[]` array as `NetworkStatusCard`. Pure function:

```ts
function pulse(lines: LineStatus[]) {
  const tube = lines.filter(l => l.mode === "tube");
  const goodTube = tube.filter(l => l.status_severity === 10).length;
  const goodAll = lines.filter(l => l.status_severity === 10).length;
  const bySeverity = bucketSeverity(lines); // good / minor / severe
  return { tube: { good: goodTube, total: tube.length }, all: { good: goodAll, total: lines.length }, bySeverity };
}
```

`status_severity === 10` is TfL's enum value for "Good Service". The buckets `bySeverity` map to the traffic-light tally (severities 0–6 = severe red, 7–9 = minor amber, 10 = green, 11–20 = informational neutral).

---

## 4. Components — detailed contracts

### 4.1 `<NetworkStatusCard>`

| Prop | Type | Notes |
|---|---|---|
| `lines` | `LineStatus[]` | All lines for all modes; the card filters internally by `selectedMode`. |
| `lastUpdated` | `Date` | For the "Updated 12 s ago" caption. |

Behaviour:
- Renders a tab strip (Tube / Elizabeth / Overground / DLR / Tram·River·Cable / Bus) and a 3-column responsive grid (`md:grid-cols-2 lg:grid-cols-3`).
- Each line cell shows: name, severity badge ("Good service" / "Minor delays" / etc.) and the TfL brand-correct mode label (the `MODE_LABELS` map currently in `app/page.tsx` relocates into `web/lib/labels.ts` so both `NetworkStatusCard` and any future card can import it).
- Empty state ("No lines reported for *Bus*"): muted alert.
- Error state delegated to the parent via `errorBoundary`-style prop or a Suspense fallback.

### 4.2 `<HappeningNowCard>` and `<ComingUpCard>`

Both consume `disruptions: Disruption[]` and filter client-side:

- `HappeningNow`: `category in {"RealTime", "Incident"}`. Sort by `last_update DESC`.
- `ComingUp`: `category === "PlannedWork"`. Sort by `created ASC`. Limit to 5.

Each disruption renders as a coloured side-bar card (severity = red, planned = indigo) with summary, description (truncated to 2 lines, expandable), `affected_routes` badges, and a relative timestamp. `closure_text` if present surfaces in a destructive `Alert`.

### 4.3 `<NetworkPulseTile>`

| Prop | Type |
|---|---|
| `lines` | `LineStatus[]` |

Layout:
```
┌────────────────────────────────────────────────────────────────┐
│ NETWORK PULSE                                                  │
│ 8 of 11  Tube lines        ● 8  ● 1  ● 2     147 of 168        │
│ running good service        green amber red   all modes · 87.5%│
└────────────────────────────────────────────────────────────────┘
```

### 4.4 `<ChatPanel>`

Thin shell that renders `<ChatView />` (TM-E3 unchanged) with sticky positioning and a card border. Future hook: pass an optional `routeContext` prop — *not used in v1*.

**Mobile behaviour (`<lg`):** `<ChatPanel>` swaps its sticky-aside layout for a Radix `Drawer` (or shadcn `Drawer` re-export) anchored to the bottom of the viewport, opened by a circular floating-action button fixed to `bottom-6 right-6`. Drawer height = `60vh` to leave the cards visible behind. The same `<ChatView>` instance is mounted inside; no duplicate state. The breakpoint switch is purely CSS-driven where possible (`hidden lg:block` for the sticky aside, `lg:hidden` for the FAB) so React doesn't unmount and lose the conversation when a user resizes the window.

### 4.5 `useAutoRefresh<T>(fetcher, intervalMs)`

```ts
function useAutoRefresh<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
): { data: T | null; error: Error | null; lastUpdated: Date | null };
```

Internals:
- `useEffect` that calls `fetcher()` once on mount, then every `intervalMs` via `setInterval`.
- Cleans up the interval on unmount and aborts in-flight requests via `AbortController`.
- Pauses the interval when `document.visibilityState !== "visible"` (battery-friendly + avoids redundant requests when the user has the tab in the background).

Handwritten on purpose — pulling SWR or React Query for two endpoints would violate the "lean by default" principle.

---

## 5. Error handling & loading

| Layer | Behaviour |
|---|---|
| Initial load (no data yet) | Each card shows a `<Skeleton>` placeholder matching its final shape (3-col grid for Network status, 3 stub rows for disruption cards, a single 60 px strip for the pulse). |
| Stale data + new fetch fails | The card keeps showing the last known data and surfaces a small inline `Alert` ("Couldn't refresh — last good 2 min ago"). No catastrophic empty state. |
| Endpoint missing config (503 from API when `DATABASE_URL` is unset locally) | Each card surfaces a friendly RFC 7807 `detail` from `ApiError`, similar to TM-E1b's pattern. |
| Chat agent unavailable (503 from `/chat/stream`) | TM-E3 already handles this — top-of-card alert "Agent unavailable". No change. |

---

## 6. Testing strategy

| Layer | Coverage |
|---|---|
| `useAutoRefresh` hook | Unit (Vitest + fake timers): initial fetch, interval re-fetch, cleanup on unmount, pause on `visibilitychange`, abort on unmount. ≥ 5 cases. |
| `NetworkStatusCard` | RTL: tab switches, empty mode, full mode (Tube), error fallback. ≥ 4 cases. |
| `HappeningNowCard` | RTL: filter correctness (only RealTime + Incident), sort order, empty state, closure-text alert. ≥ 4 cases. |
| `ComingUpCard` | RTL: filter (PlannedWork only), 5-item cap, empty state, sort by `created` ASC. ≥ 3 cases. |
| `NetworkPulseTile` | Pure unit on `pulse()`: tube-only count, all-mode count, traffic-light buckets, zero-line edge case. ≥ 4 cases. |
| `app/page.tsx` | RTL integration: initial render with mocked fetchers, error scenario, chat panel mounts. ≥ 3 cases. |
| Existing tests | All TM-E1b/E2/E3 tests preserved or migrated as-is to the new file paths. |

Goal: net-positive Vitest count after the migration, no regressions.

---

## 7. What we are NOT doing

- **No design polish.** Wireframe styling stays. No TfL brand colours, no dark mode, no typography rework. Defer to a follow-up WP.
- **No new backend endpoints.** Every card is fed by an endpoint shipped in TM-D2 or TM-D3.
- **No SWR / React Query / Zustand.** A 60-line custom hook covers the two polling needs.
- **No route-aware chat.** v1 is a single page; there is no "what page am I on" context to send.
- **No bus punctuality card or arrivals board.** Out of scope per D7.
- **No reliability card.** Out of scope per D6.
- **No iOS app.** Out of scope per D12; tracked separately in Linear.
- **No real-time WebSocket push.** Polling only — matches producer cadences without the complexity. WebSocket would require a new endpoint and a Redpanda → SSE bridge.
- **No localStorage chat history persistence.** Already excluded by TM-E3 and not added back here. (The mode-tab `localStorage` key in §3.5 is unrelated — it stores the last selected mode tab, not chat content.)
- **No login / accounts / personalisation.** Public anonymous portfolio site.

---

## 8. Risks & rollback

| # | Risk | Mitigation | Rollback |
|---|---|---|---|
| R1 | Auto-refresh causes excessive API load if many tabs open. | `visibilitychange` pause + 30 s / 300 s cadences match producer side. Tabs > 1 = additive but bounded; Railway/EC2 backend handles tens of req/s comfortably. | Increase intervals or remove auto-refresh. |
| R2 | `useAutoRefresh` race conditions (overlapping fetches). | `AbortController` aborts the in-flight request when a new interval tick fires before the previous resolves. | Fall back to TM-E1b's request-per-mount pattern. |
| R3 | Mode tab persistence in `localStorage` conflicts across browsers / first-visit defaults. | Default to `"tube"` if the stored value is missing or not in the enum. | Drop persistence; always default to Tube. |
| R4 | Sticky 1/3 chat overflows on very small `lg` screens (1024–1199 px). | Set a `max-h` on `<ChatPanel>` to viewport-minus-padding; allow internal scroll. | Drop `lg:sticky` and let the chat scroll with the page. |
| R5 | Cutting `/disruptions` and `/reliability` breaks any external bookmark. | `next.config.ts` permanent redirects to `/`. | Re-add the routes as thin "redirect on mount" pages. |
| R6 | The `pulse()` derivation diverges from what users see in the grid because of stale state. | Derive synchronously from the same `lines` array — single source of truth. | n/a (architecturally prevented). |

---

## 9. Settled questions (locked at design sign-off)

1. **Page `<title>`** — `"tfl-monitor — London transport pulse"`. The "Network Now" name belonged to the card-only landing; the unified dashboard rebrands.
2. **Header content** — wordmark + GitHub link + "About" sheet (Radix `Sheet`) with one-paragraph project description and a link to the OpenAPI doc. Matches the mockup.
3. **Analytics** — none. No `gtag`, no PostHog, no Plausible. Public anonymous portfolio site; observability stays at the API tier (Logfire) and agent tier (LangSmith).
4. **Disruption description truncation** — 2-line `line-clamp-2` (Tailwind plugin) by default, expanding to full text on click. Mirrors the TM-E2 pattern.
5. **Network pulse severity buckets** — bucketed by numeric `status_severity` (TfL enum):
   - **Green:** `severity ∈ {10, 18}` ("Good Service", "No Issues")
   - **Amber:** `severity ∈ {7, 8, 9, 11, 12, 13, 14, 15, 17}` (degraded but operating)
   - **Red:** `severity ∈ {0, 1, 2, 3, 4, 5, 6, 16, 20}` (severe / closed / suspended)
   - **Excluded from pulse:** `severity ∈ {19}` ("Information") — informational, no service impact
   The Tube fraction ("X of 11") counts only `severity === 10` lines so the headline number stays unambiguous.

---

## 10. Files touched (rough estimate)

| Status | Path | LoC est. |
|---|---|---|
| New | `web/components/dashboard/network-status-card.tsx` | ~120 |
| New | `web/components/dashboard/happening-now-card.tsx` | ~80 |
| New | `web/components/dashboard/coming-up-card.tsx` | ~70 |
| New | `web/components/dashboard/network-pulse-tile.tsx` | ~80 |
| New | `web/components/dashboard/chat-panel.tsx` | ~30 |
| New | `web/lib/hooks/use-auto-refresh.ts` | ~60 |
| New | 6 × test files under `__tests__/` | ~400 |
| Rewrite | `web/app/page.tsx` | ~150 (was ~135) |
| Rewrite | `web/app/__tests__/page.test.tsx` | ~120 |
| Delete | `web/app/disruptions/page.tsx` | -90 |
| Delete | `web/app/disruptions/__tests__/*` | -200 |
| Delete | `web/app/reliability/page.tsx` | -25 |
| Delete | `web/app/ask/page.tsx` | -10 |
| Modify | `web/next.config.ts` (add redirects) | +15 |
| Modify | `PROGRESS.md` (TM-E5 row) | +1 |

**Net diff:** roughly +800, -325 = ~+475 LoC. Three sub-PRs candidate split (auto-refresh hook + cards + page wire-up) to keep each ≤ 400 LoC.

---

## 11. Sign-off gate

- [x] Charter and success criteria accurate
- [x] All 12 locked decisions accepted
- [x] Component list complete
- [x] Out-of-scope list accepted
- [x] WP number `TM-E5` accepted (proposed; finalise when added to PROGRESS.md)
- [x] All §9 questions settled

Status: signed off 2026-05-03. Next step: writing-plans skill produces `TM-E5-plan.md`.
