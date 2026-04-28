/**
 * Fetcher for the `/disruptions/recent` endpoint.
 *
 * Calls the FastAPI handler exposed by TM-D3 over the shared
 * `apiFetch` helper. Mirrors `status-live.ts` so the disruption-log
 * server component can compose a real call against
 * `contracts/openapi.yaml :: get_recent_disruptions`.
 */

import { apiFetch } from "@/lib/api-client";
import type { components } from "@/lib/types";

export type Disruption = components["schemas"]["Disruption"];

/**
 * Return the most recent disruptions across the served network.
 *
 * `cache: "no-store"` opts the request out of the Next.js Data Cache
 * so the server component re-fetches on every request instead of
 * serving build-time HTML. Response shape is locked by the
 * `Disruption` schema in `contracts/openapi.yaml`.
 */
export async function getRecentDisruptions(): Promise<Disruption[]> {
	return apiFetch<Disruption[]>("/api/v1/disruptions/recent", {
		cache: "no-store",
	});
}
