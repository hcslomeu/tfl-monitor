# infra/ — production deployment

This directory holds the production deployment artifacts for tfl-monitor. The full design lives in
`.claude/specs/TM-A5-plan.md`; this README is the operator quickstart.

## Topology

- **Host:** AWS Lightsail Ubuntu 24.04 LTS, eu-west-2, $10/mo (2 GB RAM, 60 GB SSD, static IP `13.41.145.33`).
  Shared with `alpha-whale` and future portfolio tenants. Provisioning runbook is the alpha-whale
  repo's `docs/deploy.md`.
- **App dir:** `/opt/tfl-monitor/` on the host.
- **Reverse proxy / TLS:** shared Caddy at `/opt/caddy/` joins the external `caddy_net` docker
  network and reverse-proxies `tfl-monitor-api.humbertolomeu.com` → `tfl-monitor-api-1:8000`.
  Site block lives at `/opt/caddy/Caddyfile` on the host; `infra/caddyfile.snippet` is the source of
  truth for the tfl-monitor portion.
- **DNS:** Cloudflare A record `tfl-monitor-api.humbertolomeu.com` → `13.41.145.33` (DNS only, gray
  cloud). No proxy, no Origin Cert.
- **LLM:** AWS Bedrock cross-region inference profiles for Claude Sonnet 4.5 + Haiku 4.5
  (`eu.anthropic.*`), authenticated via a scoped IAM user with keys in `/opt/tfl-monitor/.env`.

## Files

| Path | Purpose |
| --- | --- |
| `docker-compose.prod.yml` | 3 services: `api`, `producers`, `consumers`. No Airflow. |
| `caddyfile.snippet` | Site block merged into `/opt/caddy/Caddyfile` once. |
| `cron.d/tfl-monitor` | Host cron entries for periodic dbt runs. |
| `.env.example` | Production env-var template. Copy to `/opt/tfl-monitor/.env` (chmod 600). |

## First deploy

```bash
ssh ubuntu@13.41.145.33 'sudo mkdir -p /opt/tfl-monitor && sudo chown ubuntu:ubuntu /opt/tfl-monitor'

# From workstation, in this repo root:
rsync -avz --delete \
  --exclude=.env --exclude=.env.* \
  --exclude=.git --exclude=node_modules --exclude=.venv --exclude=web \
  --exclude=tests --exclude=.claude \
  ./ ubuntu@13.41.145.33:/opt/tfl-monitor/

scp .env.production ubuntu@13.41.145.33:/opt/tfl-monitor/.env
ssh ubuntu@13.41.145.33 'chmod 600 /opt/tfl-monitor/.env'

ssh ubuntu@13.41.145.33 \
  'cd /opt/tfl-monitor && docker compose -f infra/docker-compose.prod.yml up -d --build'

ssh ubuntu@13.41.145.33 \
  'sudo cp /opt/tfl-monitor/infra/cron.d/tfl-monitor /etc/cron.d/tfl-monitor \
   && sudo chmod 644 /etc/cron.d/tfl-monitor'
```

Then add the Cloudflare A record and append `infra/caddyfile.snippet` to `/opt/caddy/Caddyfile`,
reloading with `docker exec shared-caddy caddy reload --config /etc/caddy/Caddyfile`.

## Subsequent deploys

GHA workflow `.github/workflows/deploy.yml` does the same rsync + `docker compose up -d --build` on
every push to `main` touching backend code. See the workflow file for the SSH-key + pinned-host-key
secret setup.

## Operations

| Task | Command |
| --- | --- |
| Tail api logs | `ssh ubuntu@13.41.145.33 'docker logs -f tfl-monitor-api-1 --tail 100'` |
| Restart api | `ssh ubuntu@13.41.145.33 'cd /opt/tfl-monitor && docker compose -f infra/docker-compose.prod.yml restart api'` |
| Manual dbt run | `ssh ubuntu@13.41.145.33 '/opt/tfl-monitor/scripts/cron-dbt-run.sh'` |
| Disk usage | `ssh ubuntu@13.41.145.33 'df -h / && docker system df'` |
