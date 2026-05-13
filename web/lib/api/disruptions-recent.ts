/**
 * Fetcher for the `/disruptions/recent` endpoint.
 *
 * Returns the most recent disruptions across the network. When
 * `USE_MOCKS` is on, the fetch path is short-circuited with a fixture
 * projected to the `Disruption` schema so the dashboard renders
 * without a live backend.
 */

import { apiFetch } from "@/lib/api-client";
import { USE_MOCKS } from "@/lib/env";
import { MOCK_DISRUPTION } from "@/lib/mocks/disruptions";
import type { components } from "@/lib/types";

export type Disruption = components["schemas"]["Disruption"];

function toMockDisruption(now: Date): Disruption {
	return {
		disruption_id: "MOCK-ELZ-001",
		category: "RealTime",
		category_description: "Real Time",
		description: MOCK_DISRUPTION.body.join("\n\n"),
		summary: MOCK_DISRUPTION.headline,
		affected_routes: ["elizabeth"],
		affected_stops: MOCK_DISRUPTION.stations.map((station) => station.code),
		closure_text: "",
		severity: 6,
		created: now.toISOString(),
		last_update: now.toISOString(),
	};
}

/**
 * Return the most recent disruptions across the served network.
 *
 * Calls `GET /api/v1/disruptions/recent` via the shared `apiFetch`
 * helper unless `USE_MOCKS` is on, in which case the function
 * resolves synchronously to a single fixture derived from
 * `MOCK_DISRUPTION`. Response shape is locked by the `Disruption`
 * schema in `contracts/openapi.yaml`.
 */
export async function getRecentDisruptions(
	signal?: AbortSignal,
): Promise<Disruption[]> {
	if (USE_MOCKS) {
		return [toMockDisruption(new Date())];
	}
	return apiFetch<Disruption[]>("/api/v1/disruptions/recent", {
		cache: "no-store",
		signal,
	});
}
