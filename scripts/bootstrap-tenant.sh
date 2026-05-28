#!/usr/bin/env bash
# One-shot host bootstrap for the tfl-monitor tenant on the shared Lightsail
# box. Idempotent: re-running has no side effects beyond ensuring the
# expected directories and log file exist. Run once from the author's
# workstation via SSH (see infra/README.md "First deploy").

set -euo pipefail

APP_DIR="/opt/tfl-monitor"
LOG_FILE="${APP_DIR}/cron.log"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "ERROR: ${APP_DIR} missing — rsync the repo tree before bootstrap" >&2
  exit 1
fi

mkdir -p "${APP_DIR}/scripts"
# Guard against `set -e` aborting when no scripts have been rsynced yet
# (e.g. bootstrap run before deploy.sh). `find -exec` exits 0 on no-match.
find "${APP_DIR}/scripts" -maxdepth 1 -type f -name '*.sh' -exec chmod +x {} +

touch "${LOG_FILE}"
chown ubuntu:ubuntu "${LOG_FILE}"
chmod 644 "${LOG_FILE}"

# ADR 014 removed the recurring cron; drop any stale schedule a prior
# provision installed. dim_stations is built one-shot by scripts/deploy.sh.
sudo rm -f /etc/cron.d/tfl-monitor

if [[ ! -f "${APP_DIR}/.env" ]]; then
  echo "WARN: ${APP_DIR}/.env missing — scp it before running deploy.sh" >&2
fi

echo "[$(date -Iseconds)] bootstrap complete"
