#!/usr/bin/env bash
# Idempotent redeploy on the Lightsail box. Used both by `.github/workflows/deploy.yml`
# (over SSH) and by operators running a hot fix from the workstation. Assumes the
# repo tree has already been rsynced into /opt/tfl-monitor/.
#
# Prerequisites (one-time, before the first invocation):
#   * Cloudflare A record `tfl-monitor-api.humbertolomeu.com` -> the static IP
#   * Shared Caddy site block for that hostname appended to /opt/caddy/Caddyfile
#     and reloaded via `docker exec shared-caddy caddy reload ...`
#   * /opt/tfl-monitor/.env populated (chmod 600)
# Without those, the external healthcheck below will fail. For the very first
# deploy follow `infra/README.md` "First deploy" instead — it brings up the
# stack without depending on this script's healthchecks.
#
# Healthcheck strategy:
#   1) Internal — `docker exec` curl against the api container directly so a
#      Caddy or DNS misconfiguration is distinguishable from a container crash.
#   2) External — public URL via the shared Caddy. Fewer attempts here because
#      by the time the internal check passes, Caddy should be routing.

set -euo pipefail

APP_DIR="/opt/tfl-monitor"
COMPOSE_FILE="${APP_DIR}/infra/docker-compose.prod.yml"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-https://tfl-monitor-api.humbertolomeu.com/health}"
API_CONTAINER="tfl-monitor-api-1"

cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  echo "ERROR: ${APP_DIR}/.env missing — populate from infra/.env.example before deploying" >&2
  exit 1
fi

echo "[$(date -Iseconds)] docker compose up --build"
docker compose -f "${COMPOSE_FILE}" up -d --build

echo "[$(date -Iseconds)] internal healthcheck (docker exec ${API_CONTAINER})"
for attempt in 1 2 3 4 5; do
  if docker exec "${API_CONTAINER}" curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "[$(date -Iseconds)] container healthy"
    break
  fi
  if [[ ${attempt} -eq 5 ]]; then
    echo "ERROR: ${API_CONTAINER} did not respond to /health after 5 attempts" >&2
    exit 1
  fi
  sleep 5
done

echo "[$(date -Iseconds)] external healthcheck ${HEALTHCHECK_URL}"
for attempt in 1 2 3; do
  if curl -fsS "${HEALTHCHECK_URL}" >/dev/null; then
    echo "[$(date -Iseconds)] public URL reachable"
    exit 0
  fi
  sleep 5
done

echo "WARN: container is healthy but ${HEALTHCHECK_URL} is unreachable — check DNS / Caddy" >&2
exit 1
