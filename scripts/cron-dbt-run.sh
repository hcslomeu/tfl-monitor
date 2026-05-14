#!/usr/bin/env bash
# Cron entrypoint for periodic dbt builds on the production Lightsail box.
# Installed at /etc/cron.d/tfl-monitor via infra/cron.d/tfl-monitor.
# See ADR 006 + .claude/specs/TM-A5-plan.md decision #18.

set -euo pipefail

LOG_TAG="tfl-monitor-cron"
echo "[$(date -Iseconds)] $LOG_TAG dbt run start"

cd /opt/tfl-monitor
docker exec tfl-monitor-api-1 uv run dbt run \
  --profiles-dir /app/dbt \
  --project-dir /app/dbt

echo "[$(date -Iseconds)] $LOG_TAG dbt run done"
