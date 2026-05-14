#!/usr/bin/env bash
# Idempotent redeploy on the Lightsail box. Used both by `.github/workflows/deploy.yml`
# (over SSH) and by operators running a hot fix from the workstation. Assumes the
# repo tree has already been rsynced into /opt/tfl-monitor/.

set -euo pipefail

APP_DIR="/opt/tfl-monitor"
COMPOSE_FILE="${APP_DIR}/infra/docker-compose.prod.yml"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-https://tfl-monitor-api.humbertolomeu.com/health}"

cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  echo "ERROR: ${APP_DIR}/.env missing — populate from infra/.env.example before deploying" >&2
  exit 1
fi

echo "[$(date -Iseconds)] docker compose up --build"
docker compose -f "${COMPOSE_FILE}" up -d --build

echo "[$(date -Iseconds)] healthcheck ${HEALTHCHECK_URL}"
for attempt in 1 2 3 4 5; do
  if curl -fsS "${HEALTHCHECK_URL}" >/dev/null; then
    echo "[$(date -Iseconds)] healthy"
    exit 0
  fi
  sleep 5
done

echo "ERROR: healthcheck failed after 5 attempts" >&2
exit 1
