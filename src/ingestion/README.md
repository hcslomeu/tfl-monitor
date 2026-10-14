# src/ingestion/

The async TfL Unified API client. The streaming pipeline (the message broker,
producers, and consumers, plus the `raw.*` warehouse) was removed in ADR 014 —
the app now reads TfL state live on demand via `src/api/live.py`.

## Layout

```text
src/ingestion/
└─ tfl_client/
   ├─ client.py        # async httpx client with hand-rolled retry
   ├─ retry.py         # 429/5xx/timeout backoff
   └─ normalise.py     # tier-1 → disruption payload normalisation
```

## TflClient

`TflClient` wraps a single `httpx.AsyncClient`, authenticates via the
`app_key` query parameter (redacted in Logfire spans), and parses responses
into the tier-1 Pydantic contracts in `contracts.schemas.tfl_api`. Methods:
`fetch_line_statuses` (`/Line/Mode/{modes}/Status`), `fetch_line_disruptions`
(`?detail=true`), `fetch_arrivals`, `fetch_stop_point`, `search_stop`, and
`plan_journey`.

`normalise.disruption_payloads` builds the disruption shape that
`/api/v1/disruptions/recent` returns from a detailed line-status response;
`api.live` reuses it so the synthetic-id and affected-stop logic lives in one
place.

## Observability

`client.py` masks the `app_key` query parameter in every span it emits.

## Tests

Fixtures live under `tests/fixtures/tfl/`; tests never hit the live TfL API.
