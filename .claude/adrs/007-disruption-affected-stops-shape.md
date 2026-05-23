# 007 — `affected_stops` carries resolved station names

Status: accepted
Date: 2026-05-23

## Context

`/api/v1/disruptions/recent` previously returned `affected_stops: string[]` —
a bare list of NaPTAN codes copied straight from the TfL upstream payload.
The dashboard's `LineDetail` card showed those codes verbatim
(`940GZZLUACT` rather than "Acton Town"), which is useless without an
out-of-band lookup table the user does not have.

TM-29 adds a hybrid resolver (`src/api/stations.py`) that hits a new
`analytics.dim_stations` mart first and falls back to TfL `/StopPoint/{id}`
on miss. To carry the resolved name to the frontend without a second
round-trip per NaPTAN, the disruption response shape has to change.

## Decision

Update three contract surfaces in lockstep:

- `contracts/openapi.yaml`: introduce `AffectedStop { naptan_id: string,
  name?: string | null }` and change `Disruption.affected_stops` from
  `string[]` to `AffectedStop[]`. `name` is nullable so the resolver can
  surface a confirmed miss (warehouse empty + TfL 404) without forcing
  the API to invent a placeholder.
- `contracts/schemas/tfl_api.py`: add `TflStopPoint(naptan_id, common_name)`
  for the tier-1 wire format the new `TflClient.fetch_stop_point` parses.
  Tier-1 schemas keep `alias_generator=to_camel` so the upstream camelCase
  payload deserialises cleanly.
- Regenerate `web/lib/types.ts` via `openapi-typescript` so the frontend
  consumes the new shape through the existing `components["schemas"]`
  surface — no second source of truth.

## Consequences

- **Breaking change** for any external consumer of
  `/api/v1/disruptions/recent`. None exist today (frontend is the sole
  caller; backend pins the OpenAPI version it generates against). No
  deprecation window required.
- Frontend `disruptionToSnapshot` (`web/lib/dashboard/adapt.ts`) maps the
  new shape into `DisruptionSnapshot.stations`, falling back to the raw
  NaPTAN when `name` is null so the UI degrades gracefully on resolver
  misses rather than blanking the row.
- Resolver-side caching (process-lifetime, only 404s cached as `None`)
  keeps the upstream TfL call rate low without burning the dictionary on
  transient failures — see `src/api/stations.py` for the policy.
- Future producers that emit `affected_stops` (e.g. the planned bus-route
  enrichment) must populate the same `AffectedStop` envelope; revisit this
  ADR if a third shape variant ever lands.
