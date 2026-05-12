/**
 * Fetcher for the `/status/live` endpoint.
 *
 * TM-E1b swaps the TM-E1a mock body for a real call against the
 * FastAPI handler exposed by TM-D2. The function signature is the
 * contract — call sites in `app/page.tsx` compile unchanged.
 */

import { apiFetch } from "@/lib/api-client";
import type { components } from "@/lib/types";

export type LineStatus = components["schemas"]["LineStatus"];

/**
 * Return the current operational status for every served line.
 *
 * Calls `GET /api/v1/status/live` via the shared `apiFetch` helper,
 * which surfaces non-2xx responses as `ApiError` so the caller can
 * render a fallback. `cache: "no-store"` opts the request out of the
 * Next.js Data Cache so server components re-fetch on every request
 * instead of serving build-time HTML. Response shape is locked by the
 * `LineStatus` schema in `contracts/openapi.yaml`.
 */
export async function getStatusLive(
	signal?: AbortSignal,
): Promise<LineStatus[]> {
	return apiFetch<LineStatus[]>("/api/v1/status/live", {
		cache: "no-store",
		signal,
	});
}
