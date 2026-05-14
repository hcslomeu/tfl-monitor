#!/usr/bin/env bash
# One-shot host bootstrap for the tfl-monitor tenant on the shared Lightsail
# box. Idempotent: re-running has no side effects beyond ensuring the
# expected directories, log file, and cron entry exist. Run once from the
# author's workstation via SSH (see infra/README.md "First deploy").

set -euo pipefail

APP_DIR="/opt/tfl-monitor"
LOG_FILE="${APP_DIR}/cron.log"
CRON_SRC="${APP_DIR}/infra/cron.d/tfl-monitor"
CRON_DST="/etc/cron.d/tfl-monitor"

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

if [[ -f "${CRON_SRC}" ]]; then
  sudo cp "${CRON_SRC}" "${CRON_DST}"
  sudo chmod 644 "${CRON_DST}"
  echo "[$(date -Iseconds)] installed ${CRON_DST}"
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
  echo "WARN: ${APP_DIR}/.env missing — scp it before running deploy.sh" >&2
fi

echo "[$(date -Iseconds)] bootstrap complete"
