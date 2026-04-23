-- Raw append-only tables receiving events off Kafka.
-- Each row stores the full envelope plus the JSONB payload for downstream
-- modelling in dbt.
--
-- DB-side defaults on event_id and ingested_at harden ad-hoc inserts and
-- backfills; producers still supply explicit values off the Kafka envelope.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.line_status (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.arrivals (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.disruptions (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);
