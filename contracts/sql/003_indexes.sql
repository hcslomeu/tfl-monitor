-- BTREE on ingested_at DESC supports recency scans.
-- GIN on JSONB payload enables containment and path queries in dbt staging.

CREATE INDEX IF NOT EXISTS idx_line_status_ingested_at
    ON raw.line_status (ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_line_status_payload_gin
    ON raw.line_status USING GIN (payload);

CREATE INDEX IF NOT EXISTS idx_arrivals_ingested_at
    ON raw.arrivals (ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_arrivals_payload_gin
    ON raw.arrivals USING GIN (payload);

CREATE INDEX IF NOT EXISTS idx_disruptions_ingested_at
    ON raw.disruptions (ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_disruptions_payload_gin
    ON raw.disruptions USING GIN (payload);
