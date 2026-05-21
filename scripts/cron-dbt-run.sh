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
API_CONTAINER="${API_CONTAINER:-tfl-monitor-api-1}"
# Cap each build at 14 min so the 15-min cron tick is never starved by a
# hung `docker exec`. Without this, a stuck process would hold FD 9 forever
# and every future tick would land in the "skipping" branch above.
DBT_BUILD_TIMEOUT="${DBT_BUILD_TIMEOUT:-14m}"

# Fail loud if flock is missing — otherwise every cron tick would log
# "skipping" with exit 0 and silently disable dbt builds forever.
if ! command -v flock >/dev/null 2>&1; then
  echo "[$(date -Iseconds)] $LOG_TAG ERROR: flock not installed" >&2
  exit 127
fi

# Non-blocking flock prevents overlapping runs from piling up when a build
# takes longer than the cron interval (currently 15 min). FD 9 stays open
# for the lifetime of the script, so the lock is released on any exit.
# Append (`>>`) instead of truncate (`>`) so we never touch the file's
# contents while another process holds the lock — flock cares about the
# fd, not the bytes.
exec 9>>"$LOCK_FILE"
set +e
flock -n 9
flock_status=$?
set -e
if [[ $flock_status -eq 1 ]]; then
  # exit 1 is the documented "lock busy" return from flock -n
  echo "[$(date -Iseconds)] $LOG_TAG dbt build already running, skipping"
  exit 0
elif [[ $flock_status -ne 0 ]]; then
  # Anything else is a real error (signal, syscall failure, …)
  echo "[$(date -Iseconds)] $LOG_TAG ERROR: flock failed (exit $flock_status)" >&2
  exit $flock_status
fi

echo "[$(date -Iseconds)] $LOG_TAG dbt build start"

cd /opt/tfl-monitor
# `dbt` is on $PATH inside the container thanks to
# UV_PROJECT_ENVIRONMENT=/usr/local — no `uv run` wrapping needed.
# `timeout` exits 124 when the duration is hit and the process is killed,
# at which point our exit closes FD 9 and releases the flock for the next tick.
# Important: `docker exec` does NOT forward SIGTERM to the in-container
# process by default and runs without a TTY here, so killing the `docker
# exec` client does not reap the dbt process inside the container. After a
# timeout we therefore signal the in-container `dbt build` directly so the
# next cron tick does not race a still-running build on the same warehouse.
set +e
timeout "${DBT_BUILD_TIMEOUT}" docker exec "${API_CONTAINER}" dbt build \
  --profiles-dir /app/dbt \
  --project-dir /app/dbt \
  --target prod
dbt_status=$?
set -e
if [[ $dbt_status -eq 124 ]]; then
  echo "[$(date -Iseconds)] $LOG_TAG ERROR: dbt build timed out after ${DBT_BUILD_TIMEOUT} — killing in-container dbt" >&2
  docker exec "${API_CONTAINER}" pkill -TERM -f 'dbt build' 2>/dev/null || true
  sleep 2
  docker exec "${API_CONTAINER}" pkill -KILL -f 'dbt build' 2>/dev/null || true
  exit 124
elif [[ $dbt_status -ne 0 ]]; then
  echo "[$(date -Iseconds)] $LOG_TAG ERROR: dbt build failed (exit $dbt_status)" >&2
  exit $dbt_status
fi

echo "[$(date -Iseconds)] $LOG_TAG dbt build done"
