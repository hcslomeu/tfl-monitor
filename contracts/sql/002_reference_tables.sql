-- Reference tables loaded from static CSVs.
-- Populated by batch jobs in TM-A2 / TM-B* work packages.

CREATE SCHEMA IF NOT EXISTS ref;

CREATE TABLE IF NOT EXISTS ref.lines (
    line_id TEXT PRIMARY KEY,
    line_name TEXT NOT NULL,
    mode TEXT NOT NULL,
    colour_hex TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ref.stations (
    station_id TEXT PRIMARY KEY,
    station_name TEXT NOT NULL,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    zones TEXT,
    modes_served TEXT[],
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
