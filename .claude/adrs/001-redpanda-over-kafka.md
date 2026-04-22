# 001 — Redpanda over vanilla Apache Kafka

Status: accepted
Date: 2026-04-22

## Context

The streaming pipeline needs a Kafka-API-compatible broker locally (inside
`docker-compose`) and in production (Redpanda Cloud free tier). Running
Apache Kafka locally requires ZooKeeper or KRaft controllers, a JVM, and
careful tuning on a developer laptop. The project is a portfolio artefact:
setup friction directly hurts its storytelling value.

## Decision

Use Redpanda (`redpandadata/redpanda`) as the broker in local dev and
Redpanda Cloud Serverless in production. Clients continue to talk to the
Kafka wire protocol via `aiokafka`, so swapping back to vanilla Kafka would
require no code changes.

## Consequences

- **Pros**: single binary, no ZooKeeper/KRaft ceremony, faster boot, same
  Kafka wire protocol on local and production, free tier covers this
  workload.
- **Cons**: Redpanda's ecosystem is smaller than Apache Kafka's; if we ever
  need a feature that only ships with vanilla Kafka, a migration would be
  needed. We accept that risk because the clients speak the protocol, not
  the product.
