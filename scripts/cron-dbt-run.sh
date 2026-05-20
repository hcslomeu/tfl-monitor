#!/usr/bin/env bash
# Cron entrypoint for periodic dbt builds on the production Lightsail box.
# Installed at /etc/cron.d/tfl-monitor via infra/cron.d/tfl-monitor.
# See ADR 006 + .claude/specs/TM-A5-plan.md decision #18.
#
# `dbt build` runs models + tests + snapshots + seeds in DAG order
# with test gating, so a failing test blocks downstream models from
# materialising. A bare `dbt run` would silently skip the tests and
# let bad data cascade.

set -euo pipefail

LOG_TAG="tfl-monitor-cron"
LOCK_FILE="/tmp/tfl-monitor-dbt.lock"

# Non-blocking flock prevents overlapping runs from piling up when a build
# takes longer than the cron interval (currently 15 min). FD 9 stays open
# for the lifetime of the script, so the lock is released on any exit.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -Iseconds)] $LOG_TAG dbt build already running, skipping"
  exit 0
fi

echo "[$(date -Iseconds)] $LOG_TAG dbt build start"

cd /opt/tfl-monitor
# `dbt` is on $PATH inside the container thanks to
# UV_PROJECT_ENVIRONMENT=/usr/local — no `uv run` wrapping needed.
docker exec tfl-monitor-api-1 dbt build \
  --profiles-dir /app/dbt \
  --project-dir /app/dbt \
  --target prod

echo "[$(date -Iseconds)] $LOG_TAG dbt build done"
