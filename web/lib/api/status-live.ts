/**
 * Fetcher for the `/status/live` endpoint.
 *
 * TM-E1a ships this WP with mocked data so the Network Now view can be
 * built before the FastAPI handler is wired to Postgres. The fetcher
 * keeps a real, awaitable signature so call sites are stable: TM-E1b
 * only swaps the body, not the contract.
 */

import statusLiveMock from "@/lib/mocks/status-live.json";
import type { components } from "@/lib/types";

export type LineStatus = components["schemas"]["LineStatus"];

/**
 * Return the current operational status for every served line.
 *
 * Mock origin: `web/lib/mocks/status-live.json` — a committed fixture
 * mirroring the `LineStatus` example in `contracts/openapi.yaml`.
 *
 * TODO(TM-E1b): replace the mock body with a real call once TM-D2 wires
 * the FastAPI handler to Postgres:
 *
 *   import { apiFetch } from "@/lib/api-client";
 *   return apiFetch<LineStatus[]>("/api/v1/status/live");
 *
 * The function signature is the contract — call sites do not change.
 */
export async function getStatusLive(): Promise<LineStatus[]> {
	return statusLiveMock as unknown as LineStatus[];
}
