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
# Without pipefail wired through to every pipe stage, `docker compose up ... | tail`
# masked build failures (tail's exit 0 overrode docker's exit 1), letting the deploy
# look green while no containers actually started. Keep pipefail on for the whole
# script.

APP_DIR="/opt/tfl-monitor"
COMPOSE_FILE="${APP_DIR}/infra/docker-compose.prod.yml"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-https://tfl-monitor-api.humbertolomeu.com/health}"
API_CONTAINER="tfl-monitor-api-1"
API_SERVICE="${API_SERVICE:-api}"
# Budget for the internal healthcheck loop. 12 × 5s ≈ 60s — sized for the worst
# observed Lightsail cold-start. A separate cold-start optimisation is in
# progress; this budget remains the safety net.
MAX_ATTEMPTS=12

dump_api_logs() {
  docker compose -f "${COMPOSE_FILE}" logs --tail=200 "${API_SERVICE}" >&2 || true
}

cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  echo "ERROR: ${APP_DIR}/.env missing — populate from infra/.env.example before deploying" >&2
  exit 1
fi

# Reinstall the cron schedule + log-rotation policy on every deploy.
# bootstrap-tenant.sh only runs once on first provisioning, so without this
# step changes in the repo never reach /etc on the box. `install` is one
# atomic rename, so cron/logrotate never read a half-written file mid-update.
# The step runs before `compose up` so a failing build does not also block
# host-config updates.
echo "[$(date -Iseconds)] installing cron schedule"
sudo install -m 644 "${APP_DIR}/infra/cron.d/tfl-monitor" /etc/cron.d/tfl-monitor
echo "[$(date -Iseconds)] installing logrotate policy"
sudo install -m 644 "${APP_DIR}/infra/logrotate.d/tfl-monitor" /etc/logrotate.d/tfl-monitor

echo "[$(date -Iseconds)] docker compose up --build"
docker compose -f "${COMPOSE_FILE}" up -d --build

# Post-up assertion: confirm the api container is actually running before we
# attempt healthchecks. `docker compose up` can exit 0 even when a service's
# container immediately crash-loops, and the internal healthcheck below would
# then loop on a `docker exec` against a non-running container with confusing
# output. List running services explicitly and fail fast if api is absent.
echo "[$(date -Iseconds)] verifying api service is running"
running_services="$(docker compose -f "${COMPOSE_FILE}" ps --status running --services)"
if ! grep -qx "${API_SERVICE}" <<<"${running_services}"; then
  echo "ERROR: '${API_SERVICE}' service is not running after 'docker compose up'." >&2
  echo "Running services:" >&2
  echo "${running_services:-<none>}" >&2
  docker compose -f "${COMPOSE_FILE}" ps >&2 || true
  dump_api_logs
  exit 1
fi

echo "[$(date -Iseconds)] internal healthcheck (docker exec ${API_CONTAINER})"
for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
  if docker exec "${API_CONTAINER}" curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "[$(date -Iseconds)] container healthy"
    break
  fi
  if [[ ${attempt} -eq ${MAX_ATTEMPTS} ]]; then
    echo "ERROR: ${API_CONTAINER} did not respond to /health after ${MAX_ATTEMPTS} attempts" >&2
    dump_api_logs
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
dump_api_logs
exit 1
