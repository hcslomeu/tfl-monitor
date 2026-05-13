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
	"london-overground": { code: "OVG", color: "#EE7C0E" },
};

const UNKNOWN_CODE_PREFIX = "UNK:";
const FALLBACK_COLOR = "#5A6A77";

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
 * and to the raw `valid_from` string for unparseable inputs.
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
 * looked up from the static line registry.
 */
export function lineStatusesToSummaries(lines: LineStatus[]): LineSummary[] {
	const now = new Date();
	return lines.map((line) => {
		const meta = metaFor(line.line_id);
		return {
			code: meta.code,
			name: stripTrailingLine(line.line_name),
			color: meta.color,
			status: severityToBucket(line.status_severity),
			statusText: line.status_severity_description,
			updatedLabel: relativeUpdatedLabel(line.valid_from, now),
		};
	});
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

function formatLondonTime(iso: string): string {
	try {
		return new Date(iso).toLocaleTimeString("en-GB", {
			hour: "2-digit",
			minute: "2-digit",
			timeZone: "Europe/London",
			timeZoneName: "short",
		});
	} catch {
		return iso;
	}
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

/**
 * Project a backend `Disruption` row into the view-model `LineDetail`
 * consumes. Station names degrade to the raw stop ID when we lack a
 * richer registry — Phase 5 keeps the projection minimal; richer
 * naming comes when the disruption stream is wired end-to-end.
 */
export function disruptionToSnapshot(d: Disruption): DisruptionSnapshot {
	const body = d.description
		.split(/\n{2,}/)
		.map((paragraph) => paragraph.trim())
		.filter((paragraph) => paragraph.length > 0);
	const stations = d.affected_stops.map((stop) => ({
		name: stop,
		code: stop,
	}));
	return {
		headline: d.summary,
		body,
		reportedAtLabel: formatLondonTime(d.created),
		stations,
		sourceLabel: "Source: TfL Unified API",
		updatedAtLabel: formatLondonTime(d.last_update),
	};
}
