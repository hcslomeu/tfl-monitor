# TM-E5 — Dashboard + Chat One-Pager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the four-route TfL frontend into a single `/` page that renders a 2/3 dashboard (network status + disruption cards + pulse tile) alongside a 1/3 sticky chat panel, with auto-refresh polling and mobile drawer fallback.

**Architecture:** Client-component `app/page.tsx` orchestrates two `useAutoRefresh` polling hooks (live status @ 30 s, disruptions @ 5 min) and fans the data out to four dashboard cards plus the existing TM-E3 `<ChatView />` (re-hosted in `<ChatPanel>`). All other routes (`/disruptions`, `/reliability`, `/ask`) are deleted; `next.config.ts` adds 308 redirects to `/` so external links survive.

**Tech Stack:** Next.js 16 (app router, RSC opt-out via `"use client"`), shadcn/ui (Radix primitives), Tailwind v4, Vitest + React Testing Library + jsdom, Biome (lint + format), TypeScript strict.

**Spec:** `docs/superpowers/specs/2026-05-03-dashboard-chat-design.md`

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `web/lib/labels.ts` | Pure `MODE_LABELS` map + `modeLabel()` helper, relocated from `app/page.tsx` so multiple cards can import. |
| Create | `web/lib/hooks/use-auto-refresh.ts` | Generic polling hook: `useAutoRefresh(fetcher, intervalMs)` returns `{ data, error, lastUpdated }`. Pauses on `visibilitychange`, aborts in-flight on unmount. |
| Create | `web/lib/hooks/__tests__/use-auto-refresh.test.ts` | 5 unit cases. |
| Create | `web/components/dashboard/network-pulse-tile.tsx` | Pure derivation from `LineStatus[]` → "X of Y Tube" headline + RGB tally + cross-mode total. |
| Create | `web/components/dashboard/network-status-card.tsx` | Mode tabs (Tube / Elizabeth / Overground / DLR / Tram·River·Cable / Bus) with `localStorage` persistence; line grid filtered by selected mode. |
| Create | `web/components/dashboard/happening-now-card.tsx` | Filters `disruptions[].category ∈ {RealTime, Incident}`; sort `last_update DESC`. |
| Create | `web/components/dashboard/coming-up-card.tsx` | Filters `disruptions[].category === PlannedWork`; sort `created ASC`; cap 5. |
| Create | `web/components/dashboard/chat-panel.tsx` | Sticky aside on `lg+` wrapping `<ChatView />`; FAB-triggered Drawer on `<lg`. |
| Create | `web/components/dashboard/__tests__/network-pulse-tile.test.tsx` | 4 cases. |
| Create | `web/components/dashboard/__tests__/network-status-card.test.tsx` | 5 cases. |
| Create | `web/components/dashboard/__tests__/happening-now-card.test.tsx` | 4 cases. |
| Create | `web/components/dashboard/__tests__/coming-up-card.test.tsx` | 3 cases. |
| Create | `web/components/dashboard/__tests__/chat-panel.test.tsx` | 3 cases. |
| Create | `web/components/about-sheet.tsx` | Header "About" Radix Sheet content. |
| Add (shadcn) | `web/components/ui/sheet.tsx` | shadcn primitive (CLI install). |
| Add (shadcn) | `web/components/ui/drawer.tsx` | shadcn primitive (CLI install). |
| Rewrite | `web/app/page.tsx` | One-pager orchestrator — client component, mounts hooks, renders 4 cards + chat. |
| Rewrite | `web/app/__tests__/page.test.tsx` | Integration — mocks fetchers, asserts composition. |
| Modify | `web/next.config.ts` | Adds permanent redirects from `/disruptions`, `/reliability`, `/ask` to `/`. |
| Delete | `web/app/disruptions/page.tsx` | Folded into `/`. |
| Delete | `web/app/disruptions/__tests__/` | Tests migrated into `__tests__/page.test.tsx` + `happening-now-card.test.tsx`. |
| Delete | `web/app/reliability/page.tsx` | Placeholder route removed. |
| Delete | `web/app/ask/page.tsx` | Chat reachable from `/`. |
| Modify | `PROGRESS.md` | New TM-E5 row in the table. |
| Modify | `web/components/chat-view.tsx` (light) | Optional `className` prop to allow `<ChatPanel>` to size it (no behavioural change). |

**Sub-PR sequencing:**

| PR | Tasks | Net LoC | Title |
|---|---|---|---|
| 1 | 1, 2, 3 (hook, labels, shadcn primitives) | ~+200 | `feat(web): add useAutoRefresh hook + labels module` |
| 2 | 4-9 (cards + chat panel + about sheet) | ~+550 | `feat(web): TM-E5 dashboard cards + chat panel` |
| 3 | 10-15 (page rewrite + redirects + deletions + PROGRESS) | ~+150, -325 | `feat(web): TM-E5 collapse to one-pager (closes TM-E5)` |

Each sub-PR is independently green (lint + tests). The cards in PR-2 are unused until PR-3 wires them.

---

## Pre-flight: shadcn primitives

Add the two missing primitives before Task 4 / Task 9. Run from `/Users/humbertolomeu/tfl-monitor`:

```bash
pnpm --dir web dlx shadcn@latest add sheet drawer
```

Expected: two new files appear, `web/components/ui/sheet.tsx` and `web/components/ui/drawer.tsx`. Commit them in **Task 3** below as part of the hook PR so the next PR doesn't get blocked on a primitive-only commit.

If the CLI prompts about overwriting existing files: answer **No** for all. If it asks about `lucide-react` or registry config: keep defaults (the project already pins `lucide` in `components.json`).

---

## Task 1: `useAutoRefresh` hook — write the failing test

**Files:**
- Create: `web/lib/hooks/__tests__/use-auto-refresh.test.ts`
- Test only — implementation lands in Task 2.

- [ ] **Step 1: Write the failing test file**

```ts
// web/lib/hooks/__tests__/use-auto-refresh.test.ts
import { act, renderHook, waitFor } from "@testing-library/react";
import {
	afterEach,
	beforeEach,
	describe,
	expect,
	it,
	vi,
} from "vitest";

import { useAutoRefresh } from "@/lib/hooks/use-auto-refresh";

describe("useAutoRefresh", () => {
	beforeEach(() => {
		vi.useFakeTimers();
		Object.defineProperty(document, "visibilityState", {
			configurable: true,
			value: "visible",
		});
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("calls the fetcher once on mount and exposes the result", async () => {
		const fetcher = vi.fn().mockResolvedValue({ ok: true });
		const { result } = renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => {
			expect(fetcher).toHaveBeenCalledTimes(1);
			expect(result.current.data).toEqual({ ok: true });
			expect(result.current.error).toBeNull();
			expect(result.current.lastUpdated).toBeInstanceOf(Date);
		});
	});

	it("re-fetches every interval", async () => {
		const fetcher = vi.fn().mockResolvedValue("data");
		renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

		await act(async () => {
			vi.advanceTimersByTime(1000);
			await Promise.resolve();
		});

		expect(fetcher).toHaveBeenCalledTimes(2);
	});

	it("clears the interval on unmount", async () => {
		const fetcher = vi.fn().mockResolvedValue("data");
		const { unmount } = renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
		unmount();

		act(() => {
			vi.advanceTimersByTime(5000);
		});

		expect(fetcher).toHaveBeenCalledTimes(1);
	});

	it("pauses while the document is hidden and resumes on visibility", async () => {
		const fetcher = vi.fn().mockResolvedValue("data");
		renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

		Object.defineProperty(document, "visibilityState", {
			configurable: true,
			value: "hidden",
		});
		document.dispatchEvent(new Event("visibilitychange"));

		act(() => {
			vi.advanceTimersByTime(2500);
		});
		expect(fetcher).toHaveBeenCalledTimes(1);

		Object.defineProperty(document, "visibilityState", {
			configurable: true,
			value: "visible",
		});
		await act(async () => {
			document.dispatchEvent(new Event("visibilitychange"));
			await Promise.resolve();
		});

		expect(fetcher).toHaveBeenCalledTimes(2);
	});

	it("surfaces fetcher errors on the result", async () => {
		const fetcher = vi.fn().mockRejectedValue(new Error("boom"));
		const { result } = renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => {
			expect(result.current.error?.message).toBe("boom");
			expect(result.current.data).toBeNull();
		});
	});
});
```

- [ ] **Step 2: Run the test — expect failure**

```bash
pnpm --dir web exec vitest run lib/hooks/__tests__/use-auto-refresh.test.ts
```

Expected output: 5 failing tests with `Cannot find module '@/lib/hooks/use-auto-refresh'`.

---

## Task 2: `useAutoRefresh` hook — implementation

**Files:**
- Create: `web/lib/hooks/use-auto-refresh.ts`
- Test (already): `web/lib/hooks/__tests__/use-auto-refresh.test.ts`

- [ ] **Step 1: Write the implementation**

```ts
// web/lib/hooks/use-auto-refresh.ts
"use client";

import { useEffect, useRef, useState } from "react";

export interface AutoRefreshState<T> {
	data: T | null;
	error: Error | null;
	lastUpdated: Date | null;
}

/**
 * Polls `fetcher` every `intervalMs` milliseconds and exposes the
 * latest snapshot.
 *
 * - Calls once on mount, then on each tick.
 * - Pauses while `document.visibilityState !== "visible"` and resumes
 *   when the tab becomes visible again (battery-friendly + avoids
 *   redundant requests for backgrounded tabs).
 * - Aborts the in-flight request on unmount and on each new tick.
 * - Caller-supplied `fetcher` does not need to be memoised; the hook
 *   captures it through a ref so re-renders don't restart polling.
 */
export function useAutoRefresh<T>(
	fetcher: (signal: AbortSignal) => Promise<T>,
	intervalMs: number,
): AutoRefreshState<T> {
	const [data, setData] = useState<T | null>(null);
	const [error, setError] = useState<Error | null>(null);
	const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

	const fetcherRef = useRef(fetcher);
	useEffect(() => {
		fetcherRef.current = fetcher;
	}, [fetcher]);

	useEffect(() => {
		let cancelled = false;
		let timer: ReturnType<typeof setInterval> | null = null;
		let abort: AbortController | null = null;

		const run = async () => {
			abort?.abort();
			abort = new AbortController();
			try {
				const next = await fetcherRef.current(abort.signal);
				if (cancelled) return;
				setData(next);
				setError(null);
				setLastUpdated(new Date());
			} catch (err) {
				if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
				setError(err instanceof Error ? err : new Error(String(err)));
			}
		};

		const start = () => {
			if (timer !== null) return;
			void run();
			timer = setInterval(run, intervalMs);
		};

		const stop = () => {
			if (timer !== null) {
				clearInterval(timer);
				timer = null;
			}
		};

		const handleVisibility = () => {
			if (document.visibilityState === "visible") {
				start();
			} else {
				stop();
			}
		};

		start();
		document.addEventListener("visibilitychange", handleVisibility);

		return () => {
			cancelled = true;
			stop();
			abort?.abort();
			document.removeEventListener("visibilitychange", handleVisibility);
		};
	}, [intervalMs]);

	return { data, error, lastUpdated };
}
```

- [ ] **Step 2: Run the test — expect pass**

```bash
pnpm --dir web exec vitest run lib/hooks/__tests__/use-auto-refresh.test.ts
```

Expected: `Test Files  1 passed (1)` · `Tests  5 passed (5)`.

- [ ] **Step 3: Lint + format**

```bash
pnpm --dir web lint
```

Expected: clean (Biome).

- [ ] **Step 4: Commit (task 1 + 2 together)**

Provide this command to the author:

```bash
git add web/lib/hooks/use-auto-refresh.ts web/lib/hooks/__tests__/use-auto-refresh.test.ts
git commit -m "feat(web): TM-E5 add useAutoRefresh polling hook"
```

---

## Task 3: Relocate `MODE_LABELS` + add shadcn primitives

**Files:**
- Create: `web/lib/labels.ts`
- Create: `web/lib/__tests__/labels.test.ts`
- Add via shadcn CLI: `web/components/ui/sheet.tsx`, `web/components/ui/drawer.tsx`
- Modify (in Task 11 — leave untouched here): `web/app/page.tsx`'s import

- [ ] **Step 1: Write the failing test**

```ts
// web/lib/__tests__/labels.test.ts
import { describe, expect, it } from "vitest";

import { MODE_LABELS, modeLabel } from "@/lib/labels";

describe("modeLabel", () => {
	it("returns the brand-correct label for every TfL mode", () => {
		expect(modeLabel("tube")).toBe("Tube");
		expect(modeLabel("elizabeth-line")).toBe("Elizabeth Line");
		expect(modeLabel("national-rail")).toBe("National Rail");
		expect(modeLabel("river-bus")).toBe("River Bus");
		expect(modeLabel("cable-car")).toBe("Cable Car");
	});

	it("exposes the same set of keys as the OpenAPI mode enum", () => {
		expect(Object.keys(MODE_LABELS).sort()).toEqual(
			[
				"bus",
				"cable-car",
				"dlr",
				"elizabeth-line",
				"national-rail",
				"overground",
				"river-bus",
				"tram",
				"tube",
			].sort(),
		);
	});
});
```

- [ ] **Step 2: Run — expect failure**

```bash
pnpm --dir web exec vitest run lib/__tests__/labels.test.ts
```

Expected: `Cannot find module '@/lib/labels'`.

- [ ] **Step 3: Write the implementation**

```ts
// web/lib/labels.ts
import type { LineStatus } from "@/lib/api/status-live";

export type Mode = LineStatus["mode"];

/**
 * TfL brand-correct labels for each transport mode.
 *
 * The OpenAPI enum is kebab-case (`elizabeth-line`, `national-rail`, …);
 * blindly replacing hyphens and using Tailwind `capitalize` produces
 * `Elizabeth line` and `National rail`, which both miss the brand.
 */
export const MODE_LABELS: Record<Mode, string> = {
	tube: "Tube",
	"elizabeth-line": "Elizabeth Line",
	overground: "Overground",
	dlr: "DLR",
	bus: "Bus",
	"national-rail": "National Rail",
	"river-bus": "River Bus",
	"cable-car": "Cable Car",
	tram: "Tram",
};

export function modeLabel(mode: Mode): string {
	return MODE_LABELS[mode];
}
```

- [ ] **Step 4: Run — expect pass**

```bash
pnpm --dir web exec vitest run lib/__tests__/labels.test.ts
```

Expected: `Tests  2 passed (2)`.

- [ ] **Step 5: Add shadcn primitives**

```bash
pnpm --dir web dlx shadcn@latest add sheet drawer
```

Expected: two new files written, no overwrites. If the CLI hangs waiting for input, answer "No" to every overwrite prompt.

Verify:

```bash
ls web/components/ui/sheet.tsx web/components/ui/drawer.tsx
```

Expected: both files exist.

- [ ] **Step 6: Commit**

Provide this command:

```bash
git add web/lib/labels.ts web/lib/__tests__/labels.test.ts web/components/ui/sheet.tsx web/components/ui/drawer.tsx
git commit -m "feat(web): TM-E5 relocate MODE_LABELS and add sheet+drawer primitives"
```

> **Open PR-1 here.** PR-1 contents: `useAutoRefresh` hook, `labels.ts`, two shadcn primitives. Title: `feat(web): TM-E5 add useAutoRefresh hook + labels module + shadcn primitives`.

---

## Task 4: `<NetworkPulseTile>` — failing test

**Files:**
- Create: `web/components/dashboard/__tests__/network-pulse-tile.test.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/components/dashboard/__tests__/network-pulse-tile.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NetworkPulseTile } from "@/components/dashboard/network-pulse-tile";
import type { LineStatus } from "@/lib/api/status-live";

function line(
	overrides: Partial<LineStatus> & { line_id: string; mode: LineStatus["mode"] },
): LineStatus {
	return {
		line_id: overrides.line_id,
		line_name: overrides.line_id,
		mode: overrides.mode,
		status_severity: overrides.status_severity ?? 10,
		status_severity_description:
			overrides.status_severity_description ?? "Good Service",
		reason: overrides.reason ?? null,
		valid_from: overrides.valid_from ?? "2026-05-03T00:00:00Z",
		valid_to: overrides.valid_to ?? "2026-05-03T23:59:59Z",
	};
}

describe("<NetworkPulseTile>", () => {
	it("renders the Tube fraction headline", () => {
		const lines = [
			line({ line_id: "bakerloo", mode: "tube", status_severity: 6 }),
			line({ line_id: "central", mode: "tube", status_severity: 10 }),
			line({ line_id: "circle", mode: "tube", status_severity: 10 }),
		];
		render(<NetworkPulseTile lines={lines} />);

		expect(screen.getByText(/2 of 3/)).toBeInTheDocument();
		expect(screen.getByText(/Tube lines/i)).toBeInTheDocument();
	});

	it("counts good-service across all modes for the cross-mode total", () => {
		const lines = [
			line({ line_id: "bakerloo", mode: "tube", status_severity: 10 }),
			line({ line_id: "12", mode: "bus", status_severity: 10 }),
			line({ line_id: "ncn", mode: "bus", status_severity: 6 }),
		];
		render(<NetworkPulseTile lines={lines} />);

		expect(screen.getByText(/2 of 3/i)).toBeInTheDocument();
		expect(screen.getByText(/all modes/i)).toBeInTheDocument();
	});

	it("buckets severities into red/amber/green tally with TfL boundaries", () => {
		const lines = [
			line({ line_id: "a", mode: "tube", status_severity: 0 }), // red (Special Service)
			line({ line_id: "b", mode: "tube", status_severity: 6 }), // red (Severe Delays)
			line({ line_id: "c", mode: "tube", status_severity: 9 }), // amber (Minor Delays)
			line({ line_id: "d", mode: "tube", status_severity: 10 }), // green
			line({ line_id: "e", mode: "tube", status_severity: 18 }), // green (No Issues)
			line({ line_id: "f", mode: "tube", status_severity: 19 }), // excluded (Information)
		];
		render(<NetworkPulseTile lines={lines} />);

		expect(screen.getByLabelText(/severe lines: 2/i)).toBeInTheDocument();
		expect(screen.getByLabelText(/degraded lines: 1/i)).toBeInTheDocument();
		expect(screen.getByLabelText(/good lines: 2/i)).toBeInTheDocument();
	});

	it("renders zero-state when no lines are reported", () => {
		render(<NetworkPulseTile lines={[]} />);

		expect(screen.getByText(/0 of 0/)).toBeInTheDocument();
	});
});
```

- [ ] **Step 2: Run — expect failure**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/network-pulse-tile.test.tsx
```

Expected: `Cannot find module '@/components/dashboard/network-pulse-tile'`.

---

## Task 5: `<NetworkPulseTile>` — implementation

**Files:**
- Create: `web/components/dashboard/network-pulse-tile.tsx`

- [ ] **Step 1: Write the implementation**

```tsx
// web/components/dashboard/network-pulse-tile.tsx
"use client";

import { Card } from "@/components/ui/card";
import type { LineStatus } from "@/lib/api/status-live";

interface NetworkPulseTileProps {
	lines: LineStatus[];
}

interface Pulse {
	tube: { good: number; total: number };
	all: { good: number; total: number };
	bySeverity: { severe: number; degraded: number; good: number };
}

/** Named TfL severity codes (spec §9.5). */
const TFL_SEVERITY = {
	GOOD_SERVICE: 10,
	PART_CLOSURE: 18,
	MINOR_DELAYS: 9,
	SEVERE_DELAYS: 8,
	PART_SUSPENDED: 7,
	SUSPENDED: 6,
	PLANNED_CLOSURE: 5,
	PART_WORKS: 4,
	SPECIAL_SERVICE: 3,
	REDUCED_SERVICE: 2,
	BUS_SERVICE: 1,
	CLOSED: 0,
	ISSUES: 11,
	NO_STEP_FREE: 12,
	CHANGE_OF_FREQ: 13,
	DIVERTED: 14,
	NOT_RUNNING: 15,
	RAIL_SUSP: 16,
	INFORMATION: 17,
	SPECIAL_CLOSING: 20,
} as const;

const SEVERE = new Set([
	TFL_SEVERITY.CLOSED,
	TFL_SEVERITY.BUS_SERVICE,
	TFL_SEVERITY.REDUCED_SERVICE,
	TFL_SEVERITY.SPECIAL_SERVICE,
	TFL_SEVERITY.PART_WORKS,
	TFL_SEVERITY.PLANNED_CLOSURE,
	TFL_SEVERITY.SUSPENDED,
	TFL_SEVERITY.RAIL_SUSP,
	TFL_SEVERITY.SPECIAL_CLOSING,
]);
const DEGRADED = new Set([
	TFL_SEVERITY.PART_SUSPENDED,
	TFL_SEVERITY.SEVERE_DELAYS,
	TFL_SEVERITY.MINOR_DELAYS,
	TFL_SEVERITY.ISSUES,
	TFL_SEVERITY.NO_STEP_FREE,
	TFL_SEVERITY.CHANGE_OF_FREQ,
	TFL_SEVERITY.DIVERTED,
	TFL_SEVERITY.NOT_RUNNING,
	TFL_SEVERITY.INFORMATION,
]);
const GOOD = new Set([TFL_SEVERITY.GOOD_SERVICE, TFL_SEVERITY.PART_CLOSURE]);

function pulse(lines: LineStatus[]): Pulse {
	const tube = lines.filter((l) => l.mode === "tube");
	const goodTube = tube.filter((l) => GOOD.has(l.status_severity)).length;
	const goodAll = lines.filter((l) => GOOD.has(l.status_severity)).length;

	let severe = 0;
	let degraded = 0;
	let good = 0;
	for (const l of lines) {
		if (SEVERE.has(l.status_severity)) severe += 1;
		else if (DEGRADED.has(l.status_severity)) degraded += 1;
		else if (GOOD.has(l.status_severity)) good += 1;
	}

	return {
		tube: { good: goodTube, total: tube.length },
		all: { good: goodAll, total: lines.length },
		bySeverity: { severe, degraded, good },
	};
}

export function NetworkPulseTile({ lines }: NetworkPulseTileProps) {
	const p = pulse(lines);
	const allPct =
		p.all.total > 0 ? Math.round((p.all.good / p.all.total) * 1000) / 10 : 0;

	return (
		<Card className="flex items-center gap-6 px-4 py-3">
			<div>
				<div className="text-[10px] uppercase tracking-wider text-muted-foreground">
					Network pulse
				</div>
				<div className="mt-1 text-2xl font-bold">
					{p.tube.good} of {p.tube.total}
					<span className="ml-2 text-sm font-medium text-muted-foreground">
						Tube lines
					</span>
				</div>
				<div className="text-xs text-emerald-600 dark:text-emerald-500">
					running good service
				</div>
			</div>

			<div className="flex flex-1 items-center gap-3">
				<Dot label="severe" count={p.bySeverity.severe} className="bg-red-600" />
				<Dot
					label="degraded"
					count={p.bySeverity.degraded}
					className="bg-amber-500"
				/>
				<Dot
					label="good"
					count={p.bySeverity.good}
					className="bg-emerald-600"
				/>
			</div>

			<div className="text-right text-[11px] text-muted-foreground">
				Across all served modes:
				<br />
				<b className="text-foreground">
					{p.all.good} of {p.all.total} lines · {allPct}%
				</b>
			</div>
		</Card>
	);
}

function Dot({
	label,
	count,
	className,
}: {
	label: string;
	count: number;
	className: string;
}) {
	return (
		<div
			className="flex flex-col items-center"
			aria-label={`${label} lines: ${count}`}
		>
			<span className={`size-3.5 rounded-full ${className}`} />
			<span className="mt-1 text-[10px] font-medium">{count}</span>
		</div>
	);
}
```

- [ ] **Step 2: Run — expect pass**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/network-pulse-tile.test.tsx
```

Expected: `Tests  4 passed (4)`.

- [ ] **Step 3: Commit**

Provide:

```bash
git add web/components/dashboard/network-pulse-tile.tsx web/components/dashboard/__tests__/network-pulse-tile.test.tsx
git commit -m "feat(web): TM-E5 add NetworkPulseTile dashboard card"
```

---

## Task 6: `<HappeningNowCard>` — failing test

**Files:**
- Create: `web/components/dashboard/__tests__/happening-now-card.test.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/components/dashboard/__tests__/happening-now-card.test.tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HappeningNowCard } from "@/components/dashboard/happening-now-card";
import type { Disruption } from "@/lib/api/disruptions-recent";

function disruption(over: Partial<Disruption> & { id: string }): Disruption {
	return {
		id: over.id,
		category: over.category ?? "RealTime",
		summary: over.summary ?? "Severe delays",
		description: over.description ?? "Signal failure",
		affected_routes: over.affected_routes ?? [],
		affected_stops: over.affected_stops ?? [],
		closure_text: over.closure_text ?? null,
		created: over.created ?? "2026-05-03T08:00:00Z",
		last_update: over.last_update ?? "2026-05-03T09:00:00Z",
	} as Disruption;
}

describe("<HappeningNowCard>", () => {
	it("renders only RealTime and Incident disruptions, sorted by last_update DESC", () => {
		const items: Disruption[] = [
			disruption({
				id: "a",
				category: "RealTime",
				summary: "Older RT",
				last_update: "2026-05-03T08:00:00Z",
			}),
			disruption({
				id: "b",
				category: "PlannedWork",
				summary: "Planned (excluded)",
			}),
			disruption({
				id: "c",
				category: "Incident",
				summary: "Latest incident",
				last_update: "2026-05-03T10:00:00Z",
			}),
		];
		render(<HappeningNowCard disruptions={items} />);

		const list = screen.getByRole("list");
		const rendered = within(list).getAllByRole("listitem");
		expect(rendered).toHaveLength(2);
		expect(rendered[0]).toHaveTextContent("Latest incident");
		expect(rendered[1]).toHaveTextContent("Older RT");
		expect(screen.queryByText("Planned (excluded)")).not.toBeInTheDocument();
	});

	it("shows a friendly empty state when nothing is happening", () => {
		render(<HappeningNowCard disruptions={[]} />);

		expect(screen.getByText(/all clear/i)).toBeInTheDocument();
	});

	it("surfaces closure_text in a destructive Alert", () => {
		const items = [
			disruption({
				id: "a",
				category: "RealTime",
				closure_text: "Aldgate–Baker St only",
			}),
		];
		render(<HappeningNowCard disruptions={items} />);

		expect(screen.getByText(/Aldgate–Baker St only/)).toBeInTheDocument();
	});

	it("renders affected_routes as outline badges", () => {
		const items = [
			disruption({
				id: "a",
				category: "RealTime",
				affected_routes: ["Piccadilly westbound", "Piccadilly eastbound"],
			}),
		];
		render(<HappeningNowCard disruptions={items} />);

		expect(screen.getByText("Piccadilly westbound")).toBeInTheDocument();
		expect(screen.getByText("Piccadilly eastbound")).toBeInTheDocument();
	});
});
```

- [ ] **Step 2: Run — expect failure**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/happening-now-card.test.tsx
```

Expected: `Cannot find module '@/components/dashboard/happening-now-card'`.

---

## Task 7: `<HappeningNowCard>` — implementation

**Files:**
- Create: `web/components/dashboard/happening-now-card.tsx`

- [ ] **Step 1: Write the implementation**

```tsx
// web/components/dashboard/happening-now-card.tsx
"use client";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import type { Disruption } from "@/lib/api/disruptions-recent";

interface HappeningNowCardProps {
	disruptions: Disruption[];
}

const ACTIVE_CATEGORIES: ReadonlySet<Disruption["category"]> = new Set([
	"RealTime",
	"Incident",
]);

export function HappeningNowCard({ disruptions }: HappeningNowCardProps) {
	const active = useMemo(() => {
		return disruptions
			.filter((d) => ACTIVE_CATEGORIES.has(d.category))
			.sort(
				(a, b) =>
					new Date(b.last_update ?? 0).getTime() -
					new Date(a.last_update ?? 0).getTime(),
			);
	}, [disruptions]);

	return (
		<Card>
			<CardHeader>
				<CardTitle>⚠ Happening now</CardTitle>
				<CardDescription>RealTime · Incident</CardDescription>
			</CardHeader>
			<CardContent>
				{active.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						✅ All clear across the network.
					</p>
				) : (
					<ul className="flex flex-col gap-2" aria-label="Active disruptions">
						{active.map((d) => (
							<li
								key={d.id}
								className="rounded border-l-4 border-red-600 bg-red-50 p-2 dark:bg-red-950/30"
							>
								<div className="text-sm font-semibold">{d.summary}</div>
								{d.description ? (
									<p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
										{d.description}
									</p>
								) : null}
								{d.affected_routes && d.affected_routes.length > 0 ? (
									<ul
										className="mt-2 flex flex-wrap gap-1"
										aria-label="Affected routes"
									>
										{d.affected_routes.map((r) => (
											<li key={r}>
												<Badge variant="outline">{r}</Badge>
											</li>
										))}
									</ul>
								) : null}
								{d.closure_text ? (
									<Alert variant="destructive" className="mt-2">
										<AlertDescription>{d.closure_text}</AlertDescription>
									</Alert>
								) : null}
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}
```

- [ ] **Step 2: Run — expect pass**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/happening-now-card.test.tsx
```

Expected: `Tests  4 passed (4)`.

- [ ] **Step 3: Commit**

```bash
git add web/components/dashboard/happening-now-card.tsx web/components/dashboard/__tests__/happening-now-card.test.tsx
git commit -m "feat(web): TM-E5 add HappeningNowCard dashboard card"
```

---

## Task 8: `<ComingUpCard>` — failing test + implementation

**Files:**
- Create: `web/components/dashboard/__tests__/coming-up-card.test.tsx`
- Create: `web/components/dashboard/coming-up-card.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/components/dashboard/__tests__/coming-up-card.test.tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ComingUpCard } from "@/components/dashboard/coming-up-card";
import type { Disruption } from "@/lib/api/disruptions-recent";

function disruption(over: Partial<Disruption> & { id: string }): Disruption {
	return {
		id: over.id,
		category: over.category ?? "PlannedWork",
		summary: over.summary ?? "Weekend closure",
		description: over.description ?? null,
		affected_routes: over.affected_routes ?? [],
		affected_stops: over.affected_stops ?? [],
		closure_text: over.closure_text ?? null,
		created: over.created ?? "2026-05-03T00:00:00Z",
		last_update: over.last_update ?? "2026-05-03T00:00:00Z",
	} as Disruption;
}

describe("<ComingUpCard>", () => {
	it("filters to PlannedWork sorted by created ASC and caps at 5", () => {
		const items = [
			disruption({ id: "rt", category: "RealTime", summary: "RT excluded" }),
			disruption({ id: "1", created: "2026-05-08T00:00:00Z", summary: "May 8" }),
			disruption({ id: "2", created: "2026-05-09T00:00:00Z", summary: "May 9" }),
			disruption({ id: "3", created: "2026-05-15T00:00:00Z", summary: "May 15" }),
			disruption({ id: "4", created: "2026-05-16T00:00:00Z", summary: "May 16" }),
			disruption({ id: "5", created: "2026-05-17T00:00:00Z", summary: "May 17" }),
			disruption({ id: "6", created: "2026-05-20T00:00:00Z", summary: "May 20 (capped out)" }),
		];
		render(<ComingUpCard disruptions={items} />);

		const list = screen.getByRole("list", { name: /upcoming/i });
		const rendered = within(list).getAllByRole("listitem");
		expect(rendered).toHaveLength(5);
		expect(rendered[0]).toHaveTextContent("May 8");
		expect(rendered[4]).toHaveTextContent("May 17");
		expect(screen.queryByText("RT excluded")).not.toBeInTheDocument();
		expect(screen.queryByText("May 20 (capped out)")).not.toBeInTheDocument();
	});

	it("shows a friendly empty state when there is no planned work", () => {
		render(<ComingUpCard disruptions={[]} />);

		expect(screen.getByText(/no planned work/i)).toBeInTheDocument();
	});

	it("ignores other categories entirely", () => {
		const items = [
			disruption({ id: "a", category: "Information", summary: "Info note" }),
			disruption({ id: "b", category: "Incident", summary: "Incident" }),
		];
		render(<ComingUpCard disruptions={items} />);

		expect(screen.getByText(/no planned work/i)).toBeInTheDocument();
	});
});
```

- [ ] **Step 2: Run — expect failure**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/coming-up-card.test.tsx
```

Expected: `Cannot find module '@/components/dashboard/coming-up-card'`.

- [ ] **Step 3: Write the implementation**

```tsx
// web/components/dashboard/coming-up-card.tsx
"use client";

import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import type { Disruption } from "@/lib/api/disruptions-recent";

interface ComingUpCardProps {
	disruptions: Disruption[];
}

const MAX_ITEMS = 5;
const DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
	day: "2-digit",
	month: "short",
	timeZone: "Europe/London",
});

function formatStart(iso: string): string {
	return DATE_FORMATTER.format(new Date(iso));
}

export function ComingUpCard({ disruptions }: ComingUpCardProps) {
	const upcoming = disruptions
		.filter((d) => d.category === "PlannedWork")
		.sort(
			(a, b) =>
				new Date(a.created).getTime() - new Date(b.created).getTime(),
		)
		.slice(0, MAX_ITEMS);

	return (
		<Card>
			<CardHeader>
				<CardTitle>📅 Coming up</CardTitle>
				<CardDescription>Planned work · next 14 days</CardDescription>
			</CardHeader>
			<CardContent>
				{upcoming.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						No planned work scheduled.
					</p>
				) : (
					<ul
						className="flex flex-col gap-2"
						aria-label="Upcoming planned work"
					>
						{upcoming.map((d) => (
							<li
								key={d.id}
								className="rounded border-l-4 border-indigo-500 bg-indigo-50 p-2 dark:bg-indigo-950/30"
							>
								<div className="text-sm font-semibold">
									{formatStart(d.created)} · {d.summary}
								</div>
								{d.description ? (
									<p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
										{d.description}
									</p>
								) : null}
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}
```

- [ ] **Step 4: Run — expect pass**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/coming-up-card.test.tsx
```

Expected: `Tests  3 passed (3)`.

- [ ] **Step 5: Commit**

```bash
git add web/components/dashboard/coming-up-card.tsx web/components/dashboard/__tests__/coming-up-card.test.tsx
git commit -m "feat(web): TM-E5 add ComingUpCard dashboard card"
```

---

## Task 9: `<NetworkStatusCard>` — failing test

**Files:**
- Create: `web/components/dashboard/__tests__/network-status-card.test.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/components/dashboard/__tests__/network-status-card.test.tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { NetworkStatusCard } from "@/components/dashboard/network-status-card";
import type { LineStatus } from "@/lib/api/status-live";

function line(
	id: string,
	mode: LineStatus["mode"],
	severity = 10,
	desc = "Good Service",
): LineStatus {
	return {
		line_id: id,
		line_name: id,
		mode,
		status_severity: severity,
		status_severity_description: desc,
		reason: null,
		valid_from: "2026-05-03T00:00:00Z",
		valid_to: "2026-05-03T23:59:59Z",
	};
}

describe("<NetworkStatusCard>", () => {
	beforeEach(() => {
		localStorage.clear();
	});
	afterEach(() => {
		localStorage.clear();
	});

	it("defaults to the Tube tab and renders only Tube lines", () => {
		const lines = [
			line("piccadilly", "tube"),
			line("12", "bus"),
			line("woolwich", "elizabeth-line"),
		];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		const grid = screen.getByRole("list", { name: /tube lines/i });
		const cells = within(grid).getAllByRole("listitem");
		expect(cells).toHaveLength(1);
		expect(cells[0]).toHaveTextContent("piccadilly");
	});

	it("switches mode on tab click and persists to localStorage", async () => {
		const user = userEvent.setup();
		const lines = [
			line("piccadilly", "tube"),
			line("12", "bus"),
		];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		await user.click(screen.getByRole("tab", { name: /^bus$/i }));

		const grid = screen.getByRole("list", { name: /bus lines/i });
		expect(within(grid).getByText("12")).toBeInTheDocument();
		expect(localStorage.getItem("tfl-monitor:last-mode")).toBe("bus");
	});

	it("restores the last selected mode from localStorage on mount", () => {
		localStorage.setItem("tfl-monitor:last-mode", "elizabeth-line");
		const lines = [
			line("piccadilly", "tube"),
			line("woolwich", "elizabeth-line"),
		];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		const grid = screen.getByRole("list", { name: /elizabeth line lines/i });
		expect(within(grid).getByText("woolwich")).toBeInTheDocument();
	});

	it("falls back to Tube when localStorage holds a value not in the enum", () => {
		localStorage.setItem("tfl-monitor:last-mode", "spaceship");
		const lines = [line("piccadilly", "tube")];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		expect(screen.getByRole("list", { name: /tube lines/i })).toBeInTheDocument();
	});

	it("shows an empty-state alert when the active mode has zero lines", () => {
		const lines = [line("piccadilly", "tube")];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);
		// Switch to a mode with no data
		// (synchronously toggle via fireEvent on the tab)
		const busTab = screen.getByRole("tab", { name: /^bus$/i });
		busTab.click();

		expect(screen.getByText(/no lines reported/i)).toBeInTheDocument();
	});
});
```

> Note: `@testing-library/user-event` is not yet in the project deps. **Install it before running the test** (Task 11 also depends on it).

- [ ] **Step 2: Add userEvent dev dep**

```bash
pnpm --dir web add -D @testing-library/user-event
```

- [ ] **Step 3: Run — expect failure (component missing, not import missing)**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/network-status-card.test.tsx
```

Expected: `Cannot find module '@/components/dashboard/network-status-card'`.

---

## Task 10: `<NetworkStatusCard>` — implementation

**Files:**
- Create: `web/components/dashboard/network-status-card.tsx`

- [ ] **Step 1: Write the implementation**

```tsx
// web/components/dashboard/network-status-card.tsx
"use client";

import { useEffect, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { LineStatus } from "@/lib/api/status-live";
import { modeLabel } from "@/lib/labels";

const STORAGE_KEY = "tfl-monitor:last-mode";

interface NetworkStatusCardProps {
	lines: LineStatus[];
	lastUpdated: Date | null;
}

type TabId =
	| "tube"
	| "elizabeth-line"
	| "overground"
	| "dlr"
	| "tram-river-cable"
	| "bus";

const TAB_ORDER: { id: TabId; label: string; modes: LineStatus["mode"][] }[] = [
	{ id: "tube", label: "Tube", modes: ["tube"] },
	{ id: "elizabeth-line", label: "Elizabeth", modes: ["elizabeth-line"] },
	{ id: "overground", label: "Overground", modes: ["overground"] },
	{ id: "dlr", label: "DLR", modes: ["dlr"] },
	{
		id: "tram-river-cable",
		label: "Tram · River · Cable",
		modes: ["tram", "river-bus", "cable-car", "national-rail"],
	},
	{ id: "bus", label: "Bus", modes: ["bus"] },
];

const VALID_TABS = new Set(TAB_ORDER.map((t) => t.id));

function readStoredTab(): TabId {
	if (typeof window === "undefined") return "tube";
	const stored = window.localStorage.getItem(STORAGE_KEY);
	return stored && VALID_TABS.has(stored as TabId) ? (stored as TabId) : "tube";
}

const SECONDS_FORMATTER = new Intl.RelativeTimeFormat("en", {
	numeric: "auto",
});

function formatLastUpdated(d: Date | null): string {
	if (!d) return "never";
	const seconds = Math.round((d.getTime() - Date.now()) / 1000);
	return SECONDS_FORMATTER.format(seconds, "second");
}

/**
 * useTicker — forces a re-render on a fixed interval so that relative-time
 * strings (e.g. "3 seconds ago") stay live between auto-refresh polls.
 *
 * Usage inside NetworkStatusCard:
 *   useTicker(1_000); // re-render every second
 *
 * Implementation note: the auto-refresh poll fires every 30 s; without this
 * ticker the "Updated X seconds ago" label would freeze between polls.
 */
function useTicker(intervalMs: number): void {
	const [, setTick] = useState(0);
	useEffect(() => {
		const id = setInterval(() => setTick((n) => n + 1), intervalMs);
		return () => clearInterval(id);
	}, [intervalMs]);
}

export function NetworkStatusCard({
	lines,
	lastUpdated,
}: NetworkStatusCardProps) {
	const [tab, setTab] = useState<TabId>("tube");

	useEffect(() => {
		setTab(readStoredTab());
	}, []);

	useTicker(1_000);

	const active = TAB_ORDER.find((t) => t.id === tab) ?? TAB_ORDER[0];
	const filtered = useMemo(
		() => lines.filter((l) => active.modes.includes(l.mode)),
		[lines, active],
	);

	function changeTab(next: string) {
		const id = next as TabId;
		if (!VALID_TABS.has(id)) return;
		setTab(id);
		try {
			window.localStorage.setItem(STORAGE_KEY, id);
		} catch {
			// localStorage may be unavailable in private mode; non-fatal.
		}
	}

	const listLabel = `${active.label} lines`;

	return (
		<Card>
			<CardHeader>
				<CardTitle>Network status</CardTitle>
				<CardDescription>
					Updated {formatLastUpdated(lastUpdated)} · auto-refresh 30 s
				</CardDescription>
			</CardHeader>
			<CardContent>
				<Tabs value={tab} onValueChange={changeTab}>
					<TabsList className="mb-3">
						{TAB_ORDER.map((t) => (
							<TabsTrigger key={t.id} value={t.id}>
								{t.label}
							</TabsTrigger>
						))}
					</TabsList>
				</Tabs>

				{filtered.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						No lines reported for {active.label}.
					</p>
				) : (
					<ul
						aria-label={listLabel}
						className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3"
					>
						{filtered.map((line) => (
							<li
								key={line.line_id}
								className="rounded border-l-4 border-emerald-600 bg-card p-2"
								data-testid={`line-${line.line_id}`}
							>
								<div className="flex items-baseline justify-between gap-2">
									<span className="text-sm font-semibold">
										{line.line_name}
									</span>
									<span className="text-[10px] text-muted-foreground">
										{modeLabel(line.mode)}
									</span>
								</div>
								<div className="mt-1">
									<StatusBadge
										severity={line.status_severity}
										description={line.status_severity_description}
									/>
								</div>
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}
```

- [ ] **Step 2: Run — expect pass**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/network-status-card.test.tsx
```

Expected: `Tests  5 passed (5)`.

- [ ] **Step 3: Commit**

```bash
git add web/components/dashboard/network-status-card.tsx web/components/dashboard/__tests__/network-status-card.test.tsx web/package.json web/pnpm-lock.yaml
git commit -m "feat(web): TM-E5 add NetworkStatusCard with mode tabs"
```

---

## Task 11: `<ChatPanel>` — failing test + implementation

**Files:**
- Create: `web/components/dashboard/__tests__/chat-panel.test.tsx`
- Create: `web/components/dashboard/chat-panel.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/components/dashboard/__tests__/chat-panel.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/chat-view", () => ({
	ChatView: () => <div data-testid="chat-view-stub">stub</div>,
}));

import { ChatPanel } from "@/components/dashboard/chat-panel";

describe("<ChatPanel>", () => {
	it("mounts ChatView inside the sticky aside on lg+", () => {
		render(<ChatPanel />);
		const stub = screen.getAllByTestId("chat-view-stub");
		// One in the aside; the drawer panel only mounts on demand
		expect(stub.length).toBeGreaterThanOrEqual(1);
	});

	it("opens the drawer when the FAB is clicked", async () => {
		const user = userEvent.setup();
		render(<ChatPanel />);

		const fab = screen.getByRole("button", { name: /open chat/i });
		await user.click(fab);

		expect(
			await screen.findByRole("dialog", { name: /ask the agent/i }),
		).toBeInTheDocument();
	});

	it("does not unmount the sticky ChatView when the drawer opens", async () => {
		const user = userEvent.setup();
		render(<ChatPanel />);

		const before = screen.getAllByTestId("chat-view-stub").length;
		const fab = screen.getByRole("button", { name: /open chat/i });
		await user.click(fab);

		const after = screen.getAllByTestId("chat-view-stub").length;
		expect(after).toBeGreaterThanOrEqual(before);
	});
});
```

- [ ] **Step 2: Run — expect failure**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/chat-panel.test.tsx
```

Expected: `Cannot find module '@/components/dashboard/chat-panel'`.

- [ ] **Step 3: Write the implementation**

```tsx
// web/components/dashboard/chat-panel.tsx
"use client";

import { MessageCircle } from "lucide-react";
import { useState } from "react";

import { ChatView } from "@/components/chat-view";
import { Button } from "@/components/ui/button";
import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
	DrawerTrigger,
} from "@/components/ui/drawer";

export function ChatPanel() {
	const [open, setOpen] = useState(false);

	return (
		<>
			{/* lg+ : sticky aside */}
			<aside
				aria-label="Agent chat"
				className="hidden lg:sticky lg:top-6 lg:flex lg:h-[calc(100vh-3rem)] lg:flex-col"
			>
				<ChatView />
			</aside>

			{/* < lg : floating action button + drawer */}
			<div className="lg:hidden">
				<Drawer open={open} onOpenChange={setOpen}>
					<DrawerTrigger asChild>
						<Button
							size="icon"
							className="fixed right-6 bottom-6 size-14 rounded-full shadow-lg"
							aria-label="Open chat"
						>
							<MessageCircle className="size-6" />
						</Button>
					</DrawerTrigger>
					<DrawerContent className="h-[60vh]">
						<DrawerHeader>
							<DrawerTitle>Ask the agent</DrawerTitle>
						</DrawerHeader>
						<div className="flex-1 overflow-hidden px-4 pb-4">
							<ChatView />
						</div>
					</DrawerContent>
				</Drawer>
			</div>
		</>
	);
}
```

- [ ] **Step 4: Run — expect pass**

```bash
pnpm --dir web exec vitest run components/dashboard/__tests__/chat-panel.test.tsx
```

Expected: `Tests  3 passed (3)`.

- [ ] **Step 5: Commit**

```bash
git add web/components/dashboard/chat-panel.tsx web/components/dashboard/__tests__/chat-panel.test.tsx
git commit -m "feat(web): TM-E5 add ChatPanel sticky aside + drawer"
```

---

## Task 12: `<AboutSheet>` — header content

**Files:**
- Create: `web/components/about-sheet.tsx`

- [ ] **Step 1: Write the implementation**

(no dedicated test — covered by the page-level integration test in Task 14)

```tsx
// web/components/about-sheet.tsx
"use client";

import { Info } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
	Sheet,
	SheetContent,
	SheetDescription,
	SheetHeader,
	SheetTitle,
	SheetTrigger,
} from "@/components/ui/sheet";

export function AboutSheet() {
	return (
		<Sheet>
			<SheetTrigger asChild>
				<Button variant="ghost" size="sm" aria-label="About this project">
					<Info className="size-4" />
					<span>About</span>
				</Button>
			</SheetTrigger>
			<SheetContent>
				<SheetHeader>
					<SheetTitle>tfl-monitor</SheetTitle>
					<SheetDescription>
						Live London transport status, planned works, and an agent that
						answers questions over TfL data and strategy documents.
					</SheetDescription>
				</SheetHeader>
				<div className="mt-6 space-y-3 text-sm">
					<p>
						Pipeline: TfL public APIs → Redpanda → Postgres (dbt) → FastAPI →
						this UI. Chat agent uses LangGraph with tool calls into the
						warehouse and a Pinecone vector store over TfL strategy PDFs.
					</p>
					<p>
						<a
							className="underline underline-offset-4"
							href="https://github.com/hcslomeu/tfl-monitor"
							target="_blank"
							rel="noreferrer"
						>
							Source on GitHub →
						</a>
					</p>
				</div>
			</SheetContent>
		</Sheet>
	);
}
```

- [ ] **Step 2: Lint**

```bash
pnpm --dir web lint
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/components/about-sheet.tsx
git commit -m "feat(web): TM-E5 add AboutSheet header content"
```

> **Open PR-2 here.** PR-2 contents: `network-pulse-tile`, `happening-now-card`, `coming-up-card`, `network-status-card`, `chat-panel`, `about-sheet`. Title: `feat(web): TM-E5 dashboard cards + chat panel`.

---

## Task 13: Rewrite `app/page.tsx` — failing integration test

**Files:**
- Create or rewrite: `web/app/__tests__/page.test.tsx`

- [ ] **Step 1: Write the integration test**

```tsx
// web/app/__tests__/page.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";

vi.mock("@/lib/api/status-live", () => ({
	getStatusLive: vi.fn().mockResolvedValue([
		{
			line_id: "piccadilly",
			line_name: "Piccadilly",
			mode: "tube",
			status_severity: 6,
			status_severity_description: "Severe Delays",
			reason: "Signal failure",
			valid_from: "2026-05-03T00:00:00Z",
			valid_to: "2026-05-03T23:59:59Z",
		},
		{
			line_id: "central",
			line_name: "Central",
			mode: "tube",
			status_severity: 10,
			status_severity_description: "Good Service",
			reason: null,
			valid_from: "2026-05-03T00:00:00Z",
			valid_to: "2026-05-03T23:59:59Z",
		},
	]),
}));

vi.mock("@/lib/api/disruptions-recent", () => ({
	getRecentDisruptions: vi.fn().mockResolvedValue([
		{
			id: "rt-1",
			category: "RealTime",
			summary: "Severe delays on Piccadilly",
			description: "Signal failure at Acton Town.",
			affected_routes: ["Piccadilly"],
			affected_stops: [],
			closure_text: null,
			created: "2026-05-03T08:00:00Z",
			last_update: "2026-05-03T09:00:00Z",
		},
		{
			id: "pw-1",
			category: "PlannedWork",
			summary: "Northern weekend closure",
			description: "Camden Town closed.",
			affected_routes: ["Northern"],
			affected_stops: [],
			closure_text: null,
			created: "2026-05-08T00:00:00Z",
			last_update: "2026-05-08T00:00:00Z",
		},
	]),
}));

vi.mock("@/components/chat-view", () => ({
	ChatView: () => <div data-testid="chat-view-stub" />,
}));

describe("HomePage (one-pager)", () => {
	beforeEach(() => {
		localStorage.clear();
	});
	afterEach(() => {
		vi.clearAllTimers();
	});

	it("renders all four dashboard cards plus the chat panel", async () => {
		render(<HomePage />);

		await waitFor(() => {
			expect(screen.getByText(/network status/i)).toBeInTheDocument();
		});

		expect(screen.getByText(/happening now/i)).toBeInTheDocument();
		expect(screen.getByText(/coming up/i)).toBeInTheDocument();
		expect(screen.getByText(/network pulse/i)).toBeInTheDocument();
		expect(screen.getAllByTestId("chat-view-stub").length).toBeGreaterThanOrEqual(
			1,
		);
	});

	it("surfaces the active disruption summary inside Happening now", async () => {
		render(<HomePage />);

		expect(
			await screen.findByText(/severe delays on piccadilly/i),
		).toBeInTheDocument();
	});

	it("renders the GitHub link in the header", async () => {
		render(<HomePage />);
		const link = await screen.findByRole("link", { name: /github/i });
		expect(link).toHaveAttribute("href", expect.stringContaining("github.com"));
	});
});
```

- [ ] **Step 2: Run — expect failure**

```bash
pnpm --dir web exec vitest run app/__tests__/page.test.tsx
```

Expected: failures (the existing `page.tsx` is the Network-Now-only landing).

---

## Task 14: Rewrite `app/page.tsx` — implementation

**Files:**
- Rewrite: `web/app/page.tsx`

- [ ] **Step 1: Replace the file with the one-pager orchestrator**

```tsx
// web/app/page.tsx
"use client";

import { Github } from "lucide-react";
import { useCallback } from "react";

import { AboutSheet } from "@/components/about-sheet";
import { ChatPanel } from "@/components/dashboard/chat-panel";
import { ComingUpCard } from "@/components/dashboard/coming-up-card";
import { HappeningNowCard } from "@/components/dashboard/happening-now-card";
import { NetworkPulseTile } from "@/components/dashboard/network-pulse-tile";
import { NetworkStatusCard } from "@/components/dashboard/network-status-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
	getRecentDisruptions,
	type Disruption,
} from "@/lib/api/disruptions-recent";
import { getStatusLive, type LineStatus } from "@/lib/api/status-live";
import { useAutoRefresh } from "@/lib/hooks/use-auto-refresh";

const STATUS_INTERVAL_MS = 30_000;
const DISRUPTIONS_INTERVAL_MS = 300_000;

export default function HomePage() {
	const fetchStatus = useCallback<() => Promise<LineStatus[]>>(
		() => getStatusLive(),
		[],
	);
	const fetchDisruptions = useCallback<() => Promise<Disruption[]>>(
		() => getRecentDisruptions(),
		[],
	);

	const status = useAutoRefresh(fetchStatus, STATUS_INTERVAL_MS);
	const disruptions = useAutoRefresh(fetchDisruptions, DISRUPTIONS_INTERVAL_MS);

	return (
		<main className="mx-auto max-w-screen-2xl px-6 py-6">
			<header className="mb-6 flex items-center justify-between">
				<div>
					<h1 className="font-heading text-2xl font-semibold tracking-tight">
						tfl-monitor
					</h1>
					<p className="text-sm text-muted-foreground">
						London transport pulse
					</p>
				</div>
				<div className="flex items-center gap-2">
					<Button asChild variant="ghost" size="sm">
						<a
							href="https://github.com/hcslomeu/tfl-monitor"
							target="_blank"
							rel="noreferrer"
							aria-label="GitHub repository"
						>
							<Github className="size-4" />
							<span>GitHub</span>
						</a>
					</Button>
					<AboutSheet />
				</div>
			</header>

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
				<section className="flex flex-col gap-4">
					{status.error ? (
						<Alert role="alert">
							<AlertTitle>Live status unavailable</AlertTitle>
							<AlertDescription>{status.error.message}</AlertDescription>
						</Alert>
					) : (
						<NetworkStatusCard
							lines={status.data ?? []}
							lastUpdated={status.lastUpdated}
						/>
					)}

					<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
						{disruptions.error ? (
							<Alert role="alert" className="md:col-span-2">
								<AlertTitle>Disruptions unavailable</AlertTitle>
								<AlertDescription>
									{disruptions.error.message}
								</AlertDescription>
							</Alert>
						) : (
							<>
								<HappeningNowCard disruptions={disruptions.data ?? []} />
								<ComingUpCard disruptions={disruptions.data ?? []} />
							</>
						)}
					</div>

					<NetworkPulseTile lines={status.data ?? []} />
				</section>

				<ChatPanel />
			</div>
		</main>
	);
}
```

- [ ] **Step 2: Run page test — expect pass**

```bash
pnpm --dir web exec vitest run app/__tests__/page.test.tsx
```

Expected: `Tests  3 passed (3)`.

- [ ] **Step 3: Run the full Vitest suite to surface any cross-file regression**

```bash
pnpm --dir web test
```

Expected: all tests pass. If any TM-E2/E3 page tests fail because of route deletion, that's expected — handle in Task 15.

- [ ] **Step 4: Commit**

```bash
git add web/app/page.tsx web/app/__tests__/page.test.tsx
git commit -m "feat(web): TM-E5 collapse / to dashboard one-pager"
```

---

## Task 15: Delete legacy routes + add redirects

**Files:**
- Delete: `web/app/disruptions/page.tsx`
- Delete: `web/app/disruptions/__tests__/`
- Delete: `web/app/reliability/page.tsx`
- Delete: `web/app/ask/page.tsx`
- Modify: `web/next.config.ts`

- [ ] **Step 1: Add redirects to `next.config.ts`**

Read the current file first:

```bash
cat web/next.config.ts
```

Edit it to look like:

```ts
// web/next.config.ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
	async redirects() {
		return [
			{ source: "/disruptions", destination: "/", permanent: true },
			{ source: "/reliability", destination: "/", permanent: true },
			{ source: "/ask", destination: "/", permanent: true },
		];
	},
};

export default nextConfig;
```

If the file already has other config keys, preserve them and add only the `redirects` async function.

- [ ] **Step 2: Delete the legacy routes**

```bash
rm web/app/disruptions/page.tsx
rm -rf web/app/disruptions/__tests__
rmdir web/app/disruptions
rm web/app/reliability/page.tsx
rmdir web/app/reliability
rm web/app/ask/page.tsx
rmdir web/app/ask
```

- [ ] **Step 3: Run the full Vitest suite**

```bash
pnpm --dir web test
```

Expected: all tests pass. The deleted-page tests are gone; the new dashboard cards cover their behaviour.

- [ ] **Step 4: Run the production build to verify route table**

```bash
pnpm --dir web build
```

Expected output (paraphrase): under `Routes` only `/` should appear; the build log should mention 3 redirects.

- [ ] **Step 5: Run `make check` end-to-end**

```bash
make check
```

Expected: green. (Lint + tests + dbt-parse + Python.)

- [ ] **Step 6: Commit**

```bash
git add web/next.config.ts
git rm web/app/disruptions/page.tsx web/app/reliability/page.tsx web/app/ask/page.tsx
# git rm any tests under disruptions/__tests__ that git is still tracking
git add -A web/app
git commit -m "feat(web): TM-E5 delete legacy routes and add redirects"
```

---

## Task 16: PROGRESS.md + Linear issue

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Add the TM-E5 row**

Open `PROGRESS.md`. Insert a new row in the table, after the existing TM-E3 row, before TM-A3:

```markdown
| 6 | TM-E5 | Dashboard + chat one-pager | E-frontend | ⬜ | |
```

When the PR merges, update to:

```markdown
| 6 | TM-E5 | Dashboard + chat one-pager | E-frontend | ✅ 2026-05-XX | One-pager: `/` hosts NetworkStatusCard (mode tabs) + HappeningNowCard + ComingUpCard + NetworkPulseTile + ChatPanel; `useAutoRefresh` hook drives 30 s status polling + 300 s disruption polling, paused on `visibilitychange`; legacy `/disruptions`, `/reliability`, `/ask` deleted with permanent redirects in `next.config.ts`. |
```

(Replace the date the day the PR merges.)

- [ ] **Step 2: Final make check**

```bash
make check
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add PROGRESS.md
git commit -m "docs(progress): mark TM-E5 in flight"
```

> **Open PR-3 here.** PR-3 contents: `app/page.tsx` rewrite, route deletions, redirects, PROGRESS row. Title: `feat(web): TM-E5 collapse to one-pager (closes TM-E5)`.

---

## Task 17: Manual verification (golden path)

Not a TDD step — a **manual check before merging PR-3**. The author runs it.

- [ ] **Step 1: Boot the local stack**

```bash
make up        # docker-compose up
uv run uvicorn src.api.main:app --reload --port 8000
pnpm --dir web dev
```

- [ ] **Step 2: Open `http://localhost:3000/` on a 13″ Mac**

Verify visually:
- All four cards visible without scroll on a 13″ MBP at default zoom
- Chat input visible on the right; can submit a question and see streaming reply
- Mode tabs switch the network-status card without unmounting siblings
- Refresh the page → mode tab persisted (try selecting "Bus", reload, verify "Bus" still selected)
- Trigger an empty mode (e.g. select a tab where the API returned zero lines) → empty alert visible

- [ ] **Step 3: Resize to 1024×768 and 768×1024 (DevTools responsive)**

- 1024 px: still split 2/3 + 1/3
- 1023 px and below: cards stack; FAB visible bottom-right; click FAB → drawer with chat opens

- [ ] **Step 4: Hit the redirects**

```bash
curl -I http://localhost:3000/disruptions
```

Expected: `HTTP/1.1 308 Permanent Redirect` + `Location: /`.

Same check for `/reliability` and `/ask`.

- [ ] **Step 5: Watch auto-refresh**

In the browser dev-tools Network tab, observe:
- `/api/v1/status/live` requested every 30 s while the tab is foregrounded
- `/api/v1/disruptions/recent` requested every 5 min
- Switch to another tab for ~1 min → no requests on this tab during that time
- Switch back → an immediate fetch fires, then the cadence resumes

If anything in Tasks 17.2–17.5 fails, do not merge PR-3. File a follow-up.

---

## Self-review checklist (run before opening PR-3)

- [ ] All 13 cases in `web/components/dashboard/__tests__` + `web/lib/hooks/__tests__` + `web/lib/__tests__` pass
- [ ] `pnpm --dir web build` succeeds with only `/` in the route table
- [ ] `pnpm --dir web lint` clean (Biome)
- [ ] `make check` green at root
- [ ] Three sub-PRs are each independently green (no chained failures)
- [ ] No `Network Now`, no `Disruption Log`, no `/ask` references left in `web/`:
  ```bash
  grep -r "Network Now" web/ || echo "ok"
  grep -r "Disruption Log" web/ || echo "ok"
  grep -r "/ask" web/ || echo "ok"
  ```
  Expect `ok` for all three.
- [ ] Spec coverage:
  - Success criteria #1 → Task 17 manual check
  - Success criteria #2 → Tasks 1, 14 (auto-refresh wired)
  - Success criteria #3 → Task 9 (mode-tab test)
  - Success criteria #4 → Task 13 (page test renders chat alongside cards)
  - Success criteria #5 → Task 15 (route deletions)
  - Success criteria #6 → Task 17 manual responsive check

---

## Out-of-scope reminders (do not creep)

- No design polish (TfL brand colours, dark-mode tweaks, typography rework) — separate WP.
- No SWR / React Query — `useAutoRefresh` is the entire dependency for polling.
- No new backend endpoints.
- No iOS app (parked in Linear as TM-IOS-1 or similar).
- No reliability or bus-punctuality cards.
- No localStorage chat-history persistence.
- No real-time WebSocket push.
