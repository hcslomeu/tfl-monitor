/**
 * Fetcher for the `/status/live` endpoint.
 *
 * Returns the live operational status for every served line. When
 * `USE_MOCKS` is on, the fetch path is short-circuited with fixtures
 * projected to the `LineStatus` schema so the dashboard renders
 * without a live backend.
 */

import type { LineSummary, StatusBucket } from "@/components/dashboard/types";
import { apiFetch } from "@/lib/api-client";
import { USE_MOCKS } from "@/lib/env";
import { MOCK_LINES } from "@/lib/mocks/lines";
import type { components } from "@/lib/types";

export type LineStatus = components["schemas"]["LineStatus"];

type Mode = LineStatus["mode"];

const BUCKET_TO_SEVERITY: Record<
	StatusBucket,
	{ severity: number; description: string }
> = {
	good: { severity: 10, description: "Good Service" },
	minor: { severity: 9, description: "Minor Delays" },
	severe: { severity: 6, description: "Severe Delays" },
	suspended: { severity: 1, description: "Suspended" },
};

const CODE_TO_MODE: Record<string, Mode> = {
	ELZ: "elizabeth-line",
	DLR: "dlr",
	OVG: "overground",
};

const CODE_TO_LINE_ID: Record<string, string> = {
	BAK: "bakerloo",
	CEN: "central",
	CIR: "circle",
	DIS: "district",
	ELZ: "elizabeth",
	HAM: "hammersmith-city",
	JUB: "jubilee",
	MET: "metropolitan",
	NTH: "northern",
	PIC: "piccadilly",
	VIC: "victoria",
	WAT: "waterloo-city",
	DLR: "dlr",
	OVG: "london-overground",
};

function lineSummaryToLineStatus(line: LineSummary, now: Date): LineStatus {
	const { severity, description } = BUCKET_TO_SEVERITY[line.status];
	const start = new Date(now);
	start.setUTCHours(0, 0, 0, 0);
	const end = new Date(now);
	end.setUTCHours(23, 59, 59, 0);
	return {
		line_id: CODE_TO_LINE_ID[line.code] ?? line.code.toLowerCase(),
		line_name: line.name,
		mode: CODE_TO_MODE[line.code] ?? "tube",
		status_severity: severity,
		status_severity_description: description,
		reason: null,
		valid_from: start.toISOString(),
		valid_to: end.toISOString(),
	};
}

/**
 * Return the current operational status for every served line.
 *
 * Calls `GET /api/v1/status/live` via the shared `apiFetch` helper
 * unless `USE_MOCKS` is on, in which case the function resolves
 * synchronously to fixtures derived from `MOCK_LINES`. Response shape
 * is locked by the `LineStatus` schema in `contracts/openapi.yaml`.
 */
export async function getStatusLive(
	signal?: AbortSignal,
): Promise<LineStatus[]> {
	if (USE_MOCKS) {
		const now = new Date();
		return MOCK_LINES.map((line) => lineSummaryToLineStatus(line, now));
	}
	return apiFetch<LineStatus[]>("/api/v1/status/live", {
		cache: "no-store",
		signal,
	});
}
