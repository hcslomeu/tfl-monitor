# TM-26 — Research

**Issue:** `GET /api/v1/disruptions/recent` returns `affected_routes: []`
(and `affected_stops: []`) for every row in production.

**Goal of this document:** map every layer in the data path and prove which
layer drops the data, so Phase 2 can produce a focused fix plan.

---

## 1. Reproduction (production)

```
curl -fsS https://tfl-monitor-api.humbertolomeu.com/api/v1/disruptions/recent \
  | jq '.[0:3]'
```

All returned rows carry:

```json
{
  "disruption_id": "0276a2259b723fbe98a0fee3884a9ef6",
  "category": "RealTime",
  "description": "Waterloo and City Line: Service will resume at 06:00. ",
  "affected_routes": [],
  "affected_stops": [],
  "closure_text": "serviceClosed",
  ...
}
```

`created`/`last_update` are seconds old, so ingestion is live; the
producer is publishing. Only the two arrays are missing.

---

## 2. Layer map

| Layer | File | Behavior re. affected_routes |
|---|---|---|
| TfL API (upstream) | `/Line/Mode/{modes}/Disruption` | Returns `affectedRoutes: []` for every record (verified live, every mode). **Root cause.** |
| Tier-1 contract | `contracts/schemas/tfl_api.py::TflDisruption` | Faithfully models `affected_routes: list[dict[str, object]] = []`. No drop here. |
| Producer fetch | `src/ingestion/tfl_client/client.py::fetch_disruptions` (line 98–102) | Hits `/Line/Mode/{modes}/Disruption`. Endpoint is the source of the empty arrays. |
| Tier-1 → tier-2 normaliser | `src/ingestion/tfl_client/normalise.py::disruption_payloads` (line 138–201) + `_extract_ids` (204–217) | Extracts `lineId` from each entry. Empty in → empty out. No bug. |
| Producer publish | `src/ingestion/producers/disruptions.py::DisruptionsProducer.run_once` | Publishes payload verbatim, key=`disruption_id`. No drop. |
| Kafka → raw | `RawEventWriter` → `raw.disruptions(payload jsonb)` | JSONB preserves the empty array. No drop. |
| dbt staging | `dbt/models/staging/stg_disruptions.sql` (line 63) | `payload -> 'affected_routes' as affected_routes`. Faithful pass-through. No drop. |
| API SQL | `src/api/db.py::DISRUPTIONS_SQL` (line 186–214) + `fetch_recent_disruptions` (272–299) | Selects `affected_routes`, decodes JSONB into `list`, coerces via `_as_str_list` (259–269). Empty in → empty out. No drop. |
| API schema | `src/api/schemas.py::DisruptionResponse` | Models `affected_routes: list[str]`. No drop. |

**Conclusion:** the entire pipeline correctly forwards what TfL returns.
The empty payload is supplied by the upstream endpoint itself, not lost
in transit.

---

## 3. Upstream endpoint comparison (live, 2026-05-20)

### 3.1 `/Line/Mode/tube/Disruption` (current source)

```
$ curl -fsS https://api.tfl.gov.uk/Line/Mode/tube/Disruption \
    | jq '[.[] | {affectedRoutes: (.affectedRoutes|length), affectedStops: (.affectedStops|length)}] | .[:5]'
[
  {"affectedRoutes": 0, "affectedStops": 0},
  {"affectedRoutes": 0, "affectedStops": 0},
  {"affectedRoutes": 0, "affectedStops": 0},
  {"affectedRoutes": 0, "affectedStops": 0}
]
```

Same result for `/Line/{ids}/Disruption`, every mode (`elizabeth-line`,
`overground`, `dlr`, `bus`). The free-tier `/Disruption` family never
populates these arrays.

Committed fixture `tests/fixtures/tfl/disruptions_tube.json` matches the
live response — every record has `"affectedRoutes": []` and
`"affectedStops": []`. The fixture-based unit tests therefore pass on a
broken contract.

### 3.2 `/Line/Mode/tube/Status?detail=true` (candidate source)

```
$ curl -fsS 'https://api.tfl.gov.uk/Line/Mode/tube/Status?detail=true' \
    | jq '[.[] | .lineStatuses[] | select(.disruption != null) | {affectedRoutes: (.disruption.affectedRoutes|length), affectedStops: (.disruption.affectedStops|length), description: (.disruption.description[0:60])}] | .[:5]'
[
  {"affectedRoutes": 4,  "affectedStops": 5,  "description": "District Line: Severe delays Turnham Green and  Richmond / "},
  {"affectedRoutes": 4,  "affectedStops": 4,  "description": "District Line: Severe delays Turnham Green and  Richmond / "},
  {"affectedRoutes": 6,  "affectedStops": 10, "description": "Northern Line: Minor delays between Camden Town and Edgware"},
  {"affectedRoutes": 2,  "affectedStops": 15, "description": "Piccadilly Line: Severe delays between Acton Town and Uxb..."},
  {"affectedRoutes": 4,  "affectedStops": 12, "description": "Piccadilly Line: Severe delays between Acton Town and Uxb..."}
]
```

Category coverage matches the `/Disruption` endpoint (8 RealTime records
on each at the time of testing), so the nested form is not a strict
subset.

### 3.3 Nested disruption shape (Status?detail=true)

Top-level disruption keys:

```
["$type", "affectedRoutes", "affectedStops", "category",
 "categoryDescription", "closureText", "description"]
```

Notable differences vs. `/Disruption` payload:

| Field | `/Disruption` | nested under `Status?detail=true` |
|---|---|---|
| `type` (e.g. `lineInfo`, `routeBlocking`) | present | **absent** |
| `affectedRoutes[*].lineId` | present (but always empty array) | **absent**; entries describe route sections of the parent line |
| `affectedRoutes[*].id` | route-section id | route-section id |
| `affectedRoutes[*].routeSectionNaptanEntrySequence[*].stopPoint.naptanId` | n/a | walkable for affected stops |
| Parent context | — | nested under `Line.id` / `Line.name` — the affected line is implicit |

Sample `affectedRoutes[0]` keys: `$type, destinationName, direction, id,
isEntireRouteSection, name, originationName,
routeSectionNaptanEntrySequence`.

`affectedRoutes[0]`:

```json
{
  "id": "1673",
  "name": "Harrow & Wealdstone Underground Station - Elephant & Castle Underground Station",
  "direction": "inbound",
  "originationName": "Harrow & Wealdstone Underground Station",
  "destinationName": "Elephant & Castle Underground Station",
  "isEntireRouteSection": false,
  "routeSectionNaptanEntrySequence": [
    {"ordinal": 0, "stopPoint": {"naptanId": "940GZZLUHAW", "commonName": "Harrow & Wealdstone Underground Station", ...}},
    {"ordinal": 1, "stopPoint": {"naptanId": "940GZZLUKEN", ...}}
  ]
}
```

`affectedStops[*]` carries `naptanId` directly (verified previously on
the line-status fixture path).

---

## 4. Semantic mapping (nested form → tier-2 payload)

Given `DisruptionPayload.affected_routes: list[str] = "Line IDs impacted"`
(contract docstring), the correct extraction from a nested disruption
under a `Line` is **the parent `Line.id`**, not anything inside
`disruption.affectedRoutes`.

Two compatible interpretations of `affected_routes`:

1. **Line-level** (current contract): one entry = the parent line ID.
   Coarse but matches the contract docstring and the API/downstream
   consumers (`mart_disruptions_daily` fans out per line).
2. **Route-section level**: emit each `affectedRoutes[*].id`. Higher
   fidelity but breaks downstream joins on `line_id`.

Option 1 is the consistent fix; route-section IDs can land under a
future `affected_route_sections` column without touching the existing
contract.

For `affected_stops`: walk
`disruption.affectedRoutes[*].routeSectionNaptanEntrySequence[*].stopPoint.naptanId`
and de-duplicate. Matches the contract's `affected_stops: list[str]
= "Stop-point IDs impacted"`.

---

## 5. Side effects to address in Phase 2

1. **Synthetic ID stability.** `_synthetic_disruption_id` hashes
   `category + type + closure_text + description + sorted(affected_routes)`.
   The nested form lacks `type`, and `affected_routes` will go from
   `[]` to populated. Both changes will shift IDs across the cutover.
   A one-time backfill collision is expected and acceptable (the daily
   mart deduplicates by ID; a row that surfaces a new ID for an
   already-known disruption is harmless).
2. **`type` field replacement.** Options: (a) drop `type` from the hash
   inputs and rely on `closure_text` + description for uniqueness;
   (b) substitute a stable derivation (e.g. `routeBlocking` if
   `affectedRoutes` is non-empty, else `lineInfo`). Option (a) is
   simpler and survives any future TfL schema change.
3. **Producer cadence.** Disruptions producer polls 300 s; line-status
   producer polls 30 s. Switching the disruption source to the Status
   endpoint with `detail=true` lets the disruption producer share the
   same TfL call as line-status if we refactor — but that couples two
   topics. Keep them independent for now: each producer makes its own
   call with the new endpoint. TfL allows it within the free-tier
   rate limits.
4. **Tier-1 contracts.** Need either:
   - A new `TflLineStatusDisruption` variant carrying the richer
     nested-form payload (so `affectedRoutes` includes
     `routeSectionNaptanEntrySequence`), or
   - Extend the existing `TflLineStatusDisruption` with the missing
     fields (`affectedRoutes` shape, optional `routeSectionNaptanEntrySequence`).
5. **Fixtures.** `tests/fixtures/tfl/disruptions_tube.json` becomes
   irrelevant once the source switches. A new fixture captured from
   `/Line/Mode/tube/Status?detail=true` is needed for tests.
6. **dbt + API stay unchanged.** `stg_disruptions.sql` already exposes
   `affected_routes` JSONB; `DISRUPTIONS_SQL` already selects it;
   `DisruptionResponse` already models `list[str]`. The fix is entirely
   inside the ingestion layer.
7. **Existing tests touching disruptions.** Unit tests in
   `tests/test_normalise.py` (or wherever `disruption_payloads` is
   covered) and producer tests in `tests/ingestion/test_disruptions_producer.py`
   need refreshing against the new tier-1 fixture and the new fetcher
   shape.

---

## 6. Out-of-scope for TM-26 (to be confirmed in the plan)

- New tier-2 column `affected_route_sections`.
- Augmenting `affected_routes` with route-section granularity.
- Sharing the TfL HTTP call between the line-status and disruptions
  producers.
- Backfilling historical raw rows.

---

## 7. Open questions for Phase 2

None. The fix path is clear:

- Switch the disruption producer to consume `/Line/Mode/{modes}/Status?detail=true`.
- Walk `Line → lineStatuses[] → disruption` and emit one tier-2 payload
  per disruption, with `affected_routes = [parent Line.id]` and
  `affected_stops` collected from `routeSectionNaptanEntrySequence`.
- Drop `type` from the synthetic ID hash; rely on
  `category + closure_text + description + sorted(affected_routes) +
  sorted(affected_stops)` — the stops set disambiguates the
  TfL-observed case of two same-description disruptions on the same
  line that affect different route sections.
- Refresh fixtures; rewrite tests around the new shape.
- No DB schema change, no dbt change, no API change.
