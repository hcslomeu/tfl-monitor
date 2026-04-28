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
 * render a fallback. Response shape is locked by the `LineStatus`
 * schema in `contracts/openapi.yaml`.
 */
export async function getStatusLive(): Promise<LineStatus[]> {
	return apiFetch<LineStatus[]>("/api/v1/status/live");
}
