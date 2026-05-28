#!/usr/bin/env bash
# One-shot dbt build invoked by scripts/deploy.sh after the API container is
# healthy. Builds the tfl_stations seed and the dim_stations mart (plus their
# tests) — the only dbt artefacts left after ADR 014 removed the warehouse.
# dim_stations is static, so this runs once per deploy, not on a cron tick.

set -euo pipefail

LOG_TAG="tfl-monitor-dbt"
API_CONTAINER="${API_CONTAINER:-tfl-monitor-api-1}"
DBT_BUILD_TIMEOUT="${DBT_BUILD_TIMEOUT:-5m}"

echo "[$(date -Iseconds)] $LOG_TAG dbt build start (+dim_stations)"

# `+dim_stations` selects dim_stations and its ancestors (the tfl_stations
# seed), so `dbt build` seeds, materialises the mart, and runs both sets of
# tests in DAG order. `docker exec` does not forward SIGTERM, so on a timeout
# we signal the in-container process directly before exiting.
set +e
timeout "${DBT_BUILD_TIMEOUT}" docker exec "${API_CONTAINER}" dbt build \
  --select +dim_stations \
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
