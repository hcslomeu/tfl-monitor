# TM-27 / TM-A6 — dbt Cron Frequency: 6 h → 15 min

**Date:** 2026-05-20  
**Status:** Approved  
**Track:** A-infra  
**Linear:** TM-27

---

## Problem

`/disruptions/recent` reads from `analytics.stg_disruptions`, rebuilt by `dbt build`
every 6 hours. The disruptions producer runs every 5 min, so data is fresh in the
raw table but the API serves warehouse data up to 6 h stale.

**Target staleness:** ≤ 20 min worst-case (15 min dbt cycle + 5 min producer cycle).

---

## Design

### Files Changed

| File | Change |
|---|---|
| `infra/cron.d/tfl-monitor` | Schedule `0 */6 * * *` → `*/15 * * * *`; updated header to note dual install path (bootstrap + deploy) |
| `scripts/cron-dbt-run.sh` | Add `flock -n` guard to skip overlapping runs, with `flock` precheck + explicit exit-code handling; wrap `dbt build` in `timeout 14m` + post-timeout `pkill` of the in-container dbt process so a hung build cannot starve subsequent ticks |
| `scripts/deploy.sh` | Reinstall cron file AND new logrotate policy on every deploy using `install(1)` (atomic) — closes the deploy gap and bounds log growth |
| `infra/logrotate.d/tfl-monitor` (new) | Weekly rotation with 4-rotation retention + compression + copytruncate for `/opt/tfl-monitor/cron.log` — required by the 24× higher write rate (4 → 96 runs/day) |

---

### 1. Cron schedule (`infra/cron.d/tfl-monitor`)

Change the single cron entry from every-6-hours to every-15-minutes:

```
# Before
0 */6 * * * ubuntu /opt/tfl-monitor/scripts/cron-dbt-run.sh >> /opt/tfl-monitor/cron.log 2>&1

# After
*/15 * * * * ubuntu /opt/tfl-monitor/scripts/cron-dbt-run.sh >> /opt/tfl-monitor/cron.log 2>&1
```

Impact: 4 → 96 runs/day. All models are incremental so each run only processes
the last ~15 min of data; wall-clock time per run stays low.

---

### 2. Overlap guard (`scripts/cron-dbt-run.sh`)

Running `dbt build` every 15 min without a concurrency guard risks overlapping
executions if a build runs long (e.g. Supabase connection latency spike). A `flock -n`
on a lock file makes the second invocation a fast no-op rather than a second concurrent
build, which would saturate the shared box and produce duplicate writes.

```bash
LOCK_FILE=/tmp/tfl-monitor-dbt.lock
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -Iseconds)] $LOG_TAG dbt build already running, skipping"
  exit 0
fi
```

The lock is held for the lifetime of the script process (released on exit).
`flock -n` (non-blocking) exits immediately with code 1 if the lock is held;
wrapping the failure in an `if` and exiting 0 prevents cron from flooding
`/var/mail/ubuntu` with error messages.

`dbt build` is kept (not downgraded to `dbt run`) to preserve test gating.

---

### 3. Cron deploy gap (`scripts/deploy.sh`)

**Current gap:** `bootstrap-tenant.sh` installs `infra/cron.d/tfl-monitor` →
`/etc/cron.d/tfl-monitor` once. `deploy.sh` (run on every GHA push) never
reinstalls it, so cron schedule changes in git never reach the box automatically.

**Fix:** Add an idempotent reinstall step to `deploy.sh`, before `docker compose up`:

```bash
echo "[$(date -Iseconds)] installing cron schedule"
sudo cp "${APP_DIR}/infra/cron.d/tfl-monitor" /etc/cron.d/tfl-monitor
sudo chmod 644 /etc/cron.d/tfl-monitor
```

Placed before `compose up` so the cron schedule is updated even if the compose
step fails (cron and containers are independent concerns).

---

## Staleness Budget (post-deploy)

| Phase | Max lag |
|---|---|
| TfL API → Redpanda (producer) | 5 min |
| Redpanda → raw.disruptions (consumer) | ~5 s |
| raw → analytics.stg_disruptions (dbt build) | 15 min |
| **End-to-end worst case** | **~20 min** |
| **Average** | **~10 min** |

Previous worst-case: **6 h**.

---

## What We Are NOT Doing

- Splitting into staging-only (fast) vs full-build (slow) cron entries — adds complexity for
  modest gain given all models are incremental.
- `dbt run` without tests — explicitly rejected; CLAUDE.md warns this lets bad data cascade.
- Custom monitoring/alerting for cron failures — `cron.log` on the box is sufficient
  (rotated weekly via the new logrotate policy); Logfire spans cover individual builds.
- Changing the GHA workflow — `deploy.sh` handles the cron + logrotate reinstall, no
  workflow change needed.
- Switching cron logging to syslog/journald — `copytruncate` in the logrotate policy
  keeps the existing file-redirect setup working with no script changes.

---

## Testing

No Python or TypeScript changes; standard pytest/vitest gates do not apply.

Verification gates:
1. `bash -n scripts/cron-dbt-run.sh` — syntax check passes
2. `bash -n scripts/deploy.sh` — syntax check passes
3. Post-deploy smoke: confirm `/etc/cron.d/tfl-monitor` on the box contains `*/15`
   (visible in next GHA deploy log or via a one-time SSH session with the GHA key).
4. After the first 15-min cron tick post-deploy: `curl .../disruptions/recent | jq '.[0].last_update'`
   should show a timestamp within the last 20 min.

---

## Success Criteria

- [ ] `infra/cron.d/tfl-monitor` contains `*/15 * * * *`
- [ ] `cron-dbt-run.sh` exits 0 with "skipping" log when lock is held
- [ ] `deploy.sh` reinstalls cron file on every run
- [ ] Post-deploy: `/etc/cron.d/tfl-monitor` on box reflects new schedule
- [ ] `/disruptions/recent` `last_update` within 20 min of wall-clock time after first tick
