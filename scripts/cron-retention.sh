#!/usr/bin/env bash
# Cron entrypoint for nightly retention prune on the production
# Lightsail box. Installed at /etc/cron.d/tfl-monitor via
# infra/cron.d/tfl-monitor (next to cron-dbt-run.sh).
#
# Drops raw.* rows older than per-table windows defined in
# api.maintenance.DEFAULT_RULES, then VACUUMs each table so the dead
# tuples actually return disk pages on a near-full Supabase.

set -euo pipefail

LOG_TAG="tfl-monitor-cron-retention"
LOCK_FILE="/tmp/tfl-monitor-retention.lock"
API_CONTAINER="${API_CONTAINER:-tfl-monitor-api-1}"
# Cap each run at 10 min. The DELETE on a near-full Supabase has
# historically been the slow phase; if it stalls past 10 min something
# is wrong (lock contention, query plan regression) and the next tick
# should investigate, not pile up.
RETENTION_TIMEOUT="${RETENTION_TIMEOUT:-10m}"

if ! command -v flock >/dev/null 2>&1; then
  echo "[$(date -Iseconds)] $LOG_TAG ERROR: flock not installed" >&2
  exit 127
fi

exec 9>>"$LOCK_FILE"
set +e
flock -n 9
flock_status=$?
set -e
if [[ $flock_status -eq 1 ]]; then
  echo "[$(date -Iseconds)] $LOG_TAG retention already running, skipping"
  exit 0
elif [[ $flock_status -ne 0 ]]; then
  echo "[$(date -Iseconds)] $LOG_TAG ERROR: flock failed (exit $flock_status)" >&2
  exit $flock_status
fi

echo "[$(date -Iseconds)] $LOG_TAG retention start"

cd /opt/tfl-monitor

set +e
timeout "${RETENTION_TIMEOUT}" docker exec "${API_CONTAINER}" \
  python -m api.maintenance
retention_status=$?
set -e
if [[ $retention_status -eq 124 ]]; then
  echo "[$(date -Iseconds)] $LOG_TAG ERROR: retention timed out after ${RETENTION_TIMEOUT}" >&2
  exit 124
elif [[ $retention_status -ne 0 ]]; then
  echo "[$(date -Iseconds)] $LOG_TAG ERROR: retention failed (exit $retention_status)" >&2
  exit $retention_status
fi

echo "[$(date -Iseconds)] $LOG_TAG retention done"
