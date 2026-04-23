# 005 — DB-side defaults on raw.* tables

Status: accepted
Date: 2026-04-23

## Context

`contracts/sql/001_raw_tables.sql` defines `raw.line_status`,
`raw.arrivals`, and `raw.disruptions` as append-only landing tables for
Kafka events. Producers always ship the full envelope, but several
auxiliary paths insert rows without an explicit `event_id` or
`ingested_at`:

- Ad-hoc psql sessions during incident triage.
- Backfill scripts replaying raw JSON from MinIO into the warehouse.
- Integration tests that smoke-check the initialisation contract.

Without DB-side defaults, each of these paths has to generate UUIDs and
timestamps client-side, which diverges across callers and silently drops
rows when a caller forgets either column (the `NOT NULL` on
`ingested_at` surfaces as a blunt failure hours into a backfill).

## Decision

- Enable `pgcrypto` on the Postgres init path so `gen_random_uuid()` is
  available even on PG < 13 images (we lock to PG 16 today, but the
  extension keeps the contract portable if the image is swapped for a
  managed instance that pins a different version).
- Set `DEFAULT gen_random_uuid()` on `event_id` and
  `DEFAULT now()` on `ingested_at` across the three raw tables.
- Ship an idempotent `ALTER TABLE ... SET DEFAULT` block after each
  `CREATE TABLE IF NOT EXISTS` so existing Postgres volumes from prior
  scaffolds converge to the new contract on the next SQL re-apply —
  `CREATE TABLE IF NOT EXISTS` alone is a no-op on pre-existing tables.
- Producers continue to send explicit `event_id` and `ingested_at` off
  the Kafka envelope; the defaults are a floor, not a replacement.

## Consequences

- **Pros**: ad-hoc inserts and backfills round-trip without per-caller
  UUID/timestamp plumbing; existing dev environments converge without
  manual `docker volume rm`.
- **Cons**: `pgcrypto` is redundant on PG 13+ (`gen_random_uuid()` is
  built-in). We keep it for cross-version portability; the cost is a
  single extension row in `pg_extension`.
- **Contract surface**: schema shape unchanged — only column defaults
  change. No downstream regeneration required.
