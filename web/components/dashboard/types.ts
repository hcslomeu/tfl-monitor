/**
 * Shared shapes consumed by dashboard components.
 *
 * The shapes intentionally diverge from the auto-generated OpenAPI types
 * in `web/lib/types.ts`: components consume a denormalised view-model
 * (status bucket + display colour) rather than the raw backend payload,
 * so the same components can be hydrated by mocks or by a real fetcher
 * adapter without leaking server-side concerns.
 */

export type StatusBucket = "good" | "minor" | "severe" | "suspended";

export interface LineSummary {
	code: string;
	name: string;
	color: string;
	status: StatusBucket;
	statusText: string;
	updatedLabel: string;
	/**
	 * Free-text disruption explanation propagated from `/status/live`'s
	 * `reason` field. Null for `Good Service` lines. Used as a fallback
	 * for the LineDetail card when no matching `/disruptions/recent`
	 * row exists for the selected line.
	 */
	reason?: string | null;
	/**
	 * ISO timestamp of the underlying `LineStatus.valid_from` field —
	 * threaded so the fallback snapshot built from `reason` can render
	 * a "reported HH:MM" label without re-fetching the raw row.
	 */
	validFromIso?: string;
}

export interface StatusSummaryCounts {
	good: number;
	minor: number;
	severe: number;
	suspended: number;
}

export interface DisruptionStation {
	name: string;
	code: string;
	note?: string;
}

export interface DisruptionSnapshot {
	headline: string;
	body: string[];
	reportedAtLabel: string;
	stations: DisruptionStation[];
	sourceLabel: string;
	updatedAtLabel: string;
}

export interface BusItem {
	route: string;
	text: string;
}

export interface NewsItem {
	time: string;
	title: string;
	body: string;
}
