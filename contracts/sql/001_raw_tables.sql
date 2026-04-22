-- Raw append-only tables receiving events off Kafka.
-- Each row stores the full envelope plus the JSONB payload for downstream
-- modelling in dbt.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.line_status (
    event_id UUID PRIMARY KEY,
    ingested_at TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.arrivals (
    event_id UUID PRIMARY KEY,
    ingested_at TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.disruptions (
    event_id UUID PRIMARY KEY,
    ingested_at TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);
