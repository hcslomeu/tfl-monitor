/**
 * Adapters that bridge backend payloads (`LineStatus`, `Disruption`)
 * and the dashboard's view-model shapes (`LineSummary`,
 * `DisruptionSnapshot`).
 *
 * Components in `web/components/dashboard/*` consume denormalised
 * view-models so the same components can be hydrated by mocks or by
 * real fetchers. The lookup tables here are the contract that joins
 * canonical TfL line IDs with the colours and short codes the design
 * canvas requires.
 */

import type {
	DisruptionSnapshot,
	LineSummary,
	NewsItem,
	StatusBucket,
	StatusSummaryCounts,
} from "@/components/dashboard/types";
import type { Disruption } from "@/lib/api/disruptions-recent";
import type { LineStatus } from "@/lib/api/status-live";

interface LineMeta {
	code: string;
	color: string;
}

const LINE_META_BY_ID: Record<string, LineMeta> = {
	bakerloo: { code: "BAK", color: "#894E24" },
	central: { code: "CEN", color: "#DC241F" },
	circle: { code: "CIR", color: "#FFD329" },
	district: { code: "DIS", color: "#007D32" },
	elizabeth: { code: "ELZ", color: "#6950A1" },
	"hammersmith-city": { code: "HAM", color: "#E899A8" },
	jubilee: { code: "JUB", color: "#7B868C" },
	metropolitan: { code: "MET", color: "#751056" },
	northern: { code: "NTH", color: "#000000" },
	piccadilly: { code: "PIC", color: "#0019A8" },
	victoria: { code: "VIC", color: "#039BE5" },
	"waterloo-city": { code: "WAT", color: "#76D0BD" },
	dlr: { code: "DLR", color: "#00AFAD" },
	// Post-Nov-2024 Overground split. The legacy `london-overground`
	// line_id is kept as a defensive entry: TfL still returns it from
	// some endpoints (e.g. ad-hoc `/Disruption` payloads) and dropping
	// it would force those rows down the unknown-fallback grey path.
	"london-overground": { code: "OVG", color: "#EE7C0E" },
	liberty: { code: "LIB", color: "#61686B" },
	lioness: { code: "LIO", color: "#FAA61A" },
	mildmay: { code: "MIL", color: "#0072BC" },
	suffragette: { code: "SUF", color: "#25BD3B" },
	weaver: { code: "WEA", color: "#9B0058" },
	windrush: { code: "WIN", color: "#ED1B2D" },
};

const UNKNOWN_CODE_PREFIX = "UNK:";
const FALLBACK_COLOR = "#5A6A77";

/**
 * Display precedence for the `LineGrid` rows. Tube lines come first
 * (alphabetical by name), then the Elizabeth line, then the DLR, then
 * the Overground family (alphabetical within the group — post-2024
 * the Overground was split into Lioness, Mildmay, Suffragette, Weaver,
 * Windrush, Liberty). Any line whose `mode` is not in the array is
 * pushed past Overground, alphabetical among the unknowns.
 */
const MODE_PRECEDENCE: readonly string[] = [
	"tube",
	"elizabeth-line",
	"dlr",
	"overground",
];

function modeRank(mode: string): number {
	const index = MODE_PRECEDENCE.indexOf(mode);
	return index === -1 ? MODE_PRECEDENCE.length : index;
}

const LINE_ID_BY_CODE: Record<string, string> = Object.fromEntries(
	Object.entries(LINE_META_BY_ID).map(([id, { code }]) => [code, id]),
);

function stripTrailingLine(name: string): string {
	return name.replace(/\s*line$/i, "").trim();
}

/**
 * Project a TfL `status_severity` integer onto the four display
 * buckets the dashboard uses. Mirrors the inverse of
 * `BUCKET_TO_SEVERITY` in the mock fetcher.
 */
export function severityToBucket(severity: number): StatusBucket {
	if (severity >= 10) return "good";
	if (severity >= 7) return "minor";
	if (severity >= 4) return "severe";
	return "suspended";
}

function metaFor(lineId: string): LineMeta {
	const known = LINE_META_BY_ID[lineId];
	if (known) return known;
	return { code: `${UNKNOWN_CODE_PREFIX}${lineId}`, color: FALLBACK_COLOR };
}

/**
 * Public accessor for the line-meta registry used by chip rendering
 * (e.g. ``LineDetail`` affected-routes pills). Falls back to a sentinel
 * code + neutral colour for unknown line ids so the UI degrades
 * without throwing.
 */
export function getLineMeta(lineId: string): LineMeta {
	return metaFor(lineId);
}

function lineIdForCode(code: string): string | undefined {
	const known = LINE_ID_BY_CODE[code];
	if (known) return known;
	return code.startsWith(UNKNOWN_CODE_PREFIX)
		? code.slice(UNKNOWN_CODE_PREFIX.length)
		: undefined;
}

/**
 * Render a "updated Xm/Xh ago" label from an ISO timestamp relative
 * to `now`. Falls back to "updated just now" for sub-minute deltas
 * and for unparseable inputs (graceful UI degradation — surfacing a
 * raw ISO string in the line-grid badge would look broken).
 */
export function relativeUpdatedLabel(validFromIso: string, now: Date): string {
	const validFrom = new Date(validFromIso);
	if (Number.isNaN(validFrom.getTime())) return "updated just now";
	const deltaMs = Math.max(0, now.getTime() - validFrom.getTime());
	const minutes = Math.floor(deltaMs / 60_000);
	if (minutes < 1) return "updated just now";
	if (minutes < 60) return `updated ${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	return `updated ${hours}h ago`;
}

/**
 * Convert a list of backend `LineStatus` rows into the view-model
 * shape `LineGrid` and `TopNav` consume. Colour and short code are
 * looked up from the static line registry. `now` is injected so the
 * function stays deterministic under test and can share a clock with
 * the rest of the dashboard.
 */
export function lineStatusesToSummaries(
	lines: LineStatus[],
	now: Date = new Date(),
): LineSummary[] {
	const ordered = [...lines].sort((a, b) => {
		const rankDelta = modeRank(a.mode) - modeRank(b.mode);
		if (rankDelta !== 0) return rankDelta;
		return stripTrailingLine(a.line_name).localeCompare(
			stripTrailingLine(b.line_name),
			"en",
			{ sensitivity: "base" },
		);
	});
	return ordered.map((line) => {
		const meta = metaFor(line.line_id);
		return {
			code: meta.code,
			name: stripTrailingLine(line.line_name),
			color: meta.color,
			status: severityToBucket(line.status_severity),
			statusText: line.status_severity_description,
			updatedLabel: relativeUpdatedLabel(line.valid_from, now),
			reason: line.reason?.trim() || null,
			validFromIso: line.valid_from,
		};
	});
}

/**
 * Build a `DisruptionSnapshot` from a line's status-feed `reason` text
 * when no `/disruptions/recent` row covers the selected line.
 *
 * The TfL Unified API's `lineStatuses[].reason` is always the most
 * authoritative blurb for a non-Good Service line — `/disruptions/recent`
 * is event-style and frequently lags or omits ongoing incidents. Returns
 * `undefined` when the line has no reason text so the caller can keep
 * the "No reported disruption." copy.
 */
export function lineSummaryToFallbackSnapshot(
	summary: LineSummary,
): DisruptionSnapshot | undefined {
	const reason = summary.reason?.trim();
	if (!reason) return undefined;
	const reportedAtLabel = summary.validFromIso
		? formatLondonTime(summary.validFromIso, { withTimezoneName: true })
		: "—";
	return {
		headline: summary.statusText,
		body: splitParagraphs(reason),
		reportedAtLabel,
		stations: [],
		sourceLabel: "Source: TfL Unified API (status feed)",
		updatedAtLabel: reportedAtLabel,
	};
}

/**
 * Aggregate per-bucket counts for the top-nav status summary.
 */
export function summarizeCounts(lines: LineSummary[]): StatusSummaryCounts {
	const counts: StatusSummaryCounts = {
		good: 0,
		minor: 0,
		severe: 0,
		suspended: 0,
	};
	for (const line of lines) {
		counts[line.status] += 1;
	}
	return counts;
}

function formatLondonTime(
	iso: string,
	{ withTimezoneName = false }: { withTimezoneName?: boolean } = {},
): string {
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return "—";
	return date.toLocaleTimeString("en-GB", {
		hour: "2-digit",
		minute: "2-digit",
		timeZone: "Europe/London",
		...(withTimezoneName ? { timeZoneName: "short" } : {}),
	});
}

/**
 * Locate the disruption that matches a selected line.
 *
 * Backend `affected_routes` carries canonical line IDs (`elizabeth`,
 * `piccadilly`, …), so we resolve the selected line's ID via the
 * registry and match on that.
 */
export function disruptionForLine(
	disruptions: Disruption[],
	summary: LineSummary,
): Disruption | undefined {
	const lineId = lineIdForCode(summary.code);
	if (!lineId) return undefined;
	return disruptions.find((d) => d.affected_routes.includes(lineId));
}

const NEWS_WINDOW_MS = 12 * 60 * 60 * 1000;

/**
 * Project a list of backend `Disruption` rows into the `NewsReports`
 * view-model.
 *
 * Two filters run before projection so the news pane stays a
 * "what's happening now" surface and never echoes itself:
 *
 * 1. **12 h window** — ingestion replays the full `/Disruption` payload
 *    every cycle, so stale rows persist in the DB long after TfL has
 *    cleared them. Rows whose `last_update` is older than 12 h relative
 *    to `now` are dropped (boundary inclusive). Rows with an unparseable
 *    `last_update` are dropped because we cannot prove they are recent.
 * 2. **Content-exact dedup** — TfL re-publishes ongoing incidents on
 *    every poll (currently every 5 min), so without dedup the pane
 *    fills with N copies of the same closure within an hour. Dedup
 *    walks rows in descending `last_update` order and keeps the first
 *    occurrence of each `title|body` pair. Keying on rendered content
 *    rather than `disruption_id` also collapses cases where TfL re-issues
 *    a closure under a fresh id but with identical text.
 *
 * `time` uses the London-local `HH:MM` format the design canvas
 * specifies. The `body` carries only the *extra* paragraphs of
 * `description` — TfL's Unified API repeats `summary` as the first
 * paragraph of `description` in nearly every payload, so projecting
 * the whole description into the body produces a duplicate of the
 * title. We strip the leading paragraph when it matches `summary`
 * and join any remaining paragraphs with a blank line. `now` is
 * injected so the function stays deterministic under test.
 */
export function disruptionsToNews(
	disruptions: Disruption[],
	now: Date = new Date(),
): NewsItem[] {
	const cutoffMs = now.getTime() - NEWS_WINDOW_MS;
	const dated = disruptions
		.map((d) => ({ d, ts: Date.parse(d.last_update) }))
		.filter(({ ts }) => !Number.isNaN(ts) && ts >= cutoffMs)
		.sort((a, b) => b.ts - a.ts);

	const seen = new Set<string>();
	const items: NewsItem[] = [];
	for (const { d } of dated) {
		const { headline, body: bodyParagraphs } = chooseHeadlineAndBody(
			d.summary,
			d.description,
		);
		const body = bodyParagraphs.join("\n\n");
		// JSON.stringify guarantees a separator that cannot appear inside
		// either string verbatim, so titles ending in whitespace cannot
		// collide with bodies starting in whitespace (and vice-versa).
		const key = JSON.stringify([headline, body]);
		if (seen.has(key)) continue;
		seen.add(key);
		items.push({
			time: formatLondonTime(d.last_update),
			title: headline,
			body,
		});
	}
	return items;
}

// Matches blank-line separators in both LF and CRLF payloads. The TfL
// Unified API typically returns LF-encoded descriptions, but the schema
// does not guarantee it — defending against CRLF keeps the news list
// and the snapshot body trimmed under both line-ending conventions.
const PARAGRAPH_SPLIT_RE = /\r?\n\s*\r?\n+/;

function splitParagraphs(description: string): string[] {
	return description
		.split(PARAGRAPH_SPLIT_RE)
		.map((paragraph) => paragraph.trim())
		.filter((paragraph) => paragraph.length > 0);
}

// TfL's Unified API occasionally truncates `summary` mid-word (~250-char
// cap) while shipping the full sentence in `description`. Treating the
// truncated string as the canonical headline produces two bad outcomes:
// the LineDetail card renders the cut headline above the full sentence
// (visible echo), and dedup in `disruptionsToNews` keeps every copy
// because the truncation point varies subtly between polls.
//
// Tolerance value: characters that may differ at the truncation boundary
// before we abandon the promotion. 5 covers the common case of TfL
// cutting "Tickets" → "Tic" (3 chars match before divergence) plus a
// little slack for whitespace or hyphenation around the cut.
const TRUNCATION_TOLERANCE = 5;

// Minimum summary length before we even consider promoting the
// description's first paragraph as the headline. TfL's truncation only
// kicks in near the ~250-char cap, with the cut point landing anywhere
// in the 100-249 char range depending on word boundaries; observed
// real-world cases have ranged 150-220 chars. For shorter summaries the
// 5-char tolerance becomes a large fraction of the string and would let
// unrelated descriptions sharing just a few leading chars be wrongly
// promoted (e.g. "Closed." vs "Closure on Northern line." shares 4
// leading chars, satisfying `4 >= 7 - 5`). 100 is the empirical floor
// that catches every truncation observed in production while rejecting
// every short-sentinel case seen in fixtures.
const TRUNCATION_MIN_SUMMARY_LEN = 100;

function commonPrefixLength(a: string, b: string): number {
	const upper = Math.min(a.length, b.length);
	let i = 0;
	while (i < upper && a.charCodeAt(i) === b.charCodeAt(i)) i += 1;
	return i;
}

/**
 * Choose the canonical headline + body for a disruption.
 *
 * Returns the trimmed `summary` as headline and any paragraphs of
 * `description` past the leading echo as body. When TfL's `summary`
 * looks truncated against `description` (the two share a long common
 * prefix and `description`'s first paragraph is the longer string),
 * promote that first paragraph to the headline so the card and the
 * news pane render the full sentence instead of the cut one.
 */
function chooseHeadlineAndBody(
	summary: string,
	description: string,
): { headline: string; body: string[] } {
	const trimmedSummary = summary.trim();
	const paragraphs = splitParagraphs(description);
	if (paragraphs.length === 0) {
		return { headline: trimmedSummary, body: [] };
	}
	const head = paragraphs[0];
	if (head === trimmedSummary) {
		return { headline: trimmedSummary, body: paragraphs.slice(1) };
	}
	if (
		head.length > trimmedSummary.length &&
		// Only consider promotion when the summary is long enough to plausibly
		// have been truncated by TfL's ~250-char cap. For shorter summaries
		// the tolerance becomes a large fraction of the string and would let
		// unrelated descriptions sharing a few leading chars be wrongly promoted.
		trimmedSummary.length >= TRUNCATION_MIN_SUMMARY_LEN
	) {
		const overlap = commonPrefixLength(trimmedSummary, head);
		if (overlap >= trimmedSummary.length - TRUNCATION_TOLERANCE) {
			return { headline: head, body: paragraphs.slice(1) };
		}
	}
	return { headline: trimmedSummary, body: paragraphs };
}

/**
 * Project a backend `Disruption` row into the view-model `LineDetail`
 * consumes. Station names degrade to the raw stop ID when we lack a
 * richer registry — Phase 5 keeps the projection minimal; richer
 * naming comes when the disruption stream is wired end-to-end.
 *
 * Headline + body are picked by `chooseHeadlineAndBody`, which strips
 * the leading paragraph of `description` when it echoes `summary` and
 * promotes `description`'s first paragraph to the headline when TfL
 * ships a summary truncated mid-word.
 */
export function disruptionToSnapshot(d: Disruption): DisruptionSnapshot {
	const { headline, body } = chooseHeadlineAndBody(d.summary, d.description);
	const stations = d.affected_stops.map((stop) => ({
		name: stop.name ?? stop.naptan_id,
		code: stop.naptan_id,
	}));
	return {
		headline,
		body,
		reportedAtLabel: formatLondonTime(d.created, { withTimezoneName: true }),
		stations,
		sourceLabel: "Source: TfL Unified API",
		updatedAtLabel: formatLondonTime(d.last_update, { withTimezoneName: true }),
		closureText: d.closure_text || undefined,
		affectedRoutes:
			d.affected_routes.length > 0 ? d.affected_routes : undefined,
	};
}
