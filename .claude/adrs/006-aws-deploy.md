# 006 — AWS Bedrock + shared Lightsail deploy

Status: accepted
Date: 2026-05-15

## Context

TM-A5 ships the production deployment of tfl-monitor. Two earlier
readings of the same WP have been superseded:

- The original spec assumed an **all-AWS ECS Fargate pivot**.
  Operationally heavy for a single-tenant portfolio service with a
  ~$5/month budget.
- The interim plan (committed in PR #49) called for **EC2 t4g.small
  spot via ASG + DuckDNS + Terraform**. Spot interruptions (~5 min
  every few days) bleed into the agent's live demos, the
  Terraform-for-one-box ceremony was disproportionate, and DuckDNS
  free-tier reliability is not portfolio-grade.

By 2026-05-14 the author's portfolio had a second project
(alpha-whale) running on its own AWS Lightsail box (eu-west-2, $10/mo
plan: 2 GB RAM, 1 vCPU, 60 GB SSD, 3 TB transfer, static IP, Ubuntu
24.04 LTS). The cheapest, lowest-ceremony move was to make
tfl-monitor a second tenant on that box rather than provision a new
host.

## Decision

1. **Compute.** Deploy tfl-monitor onto the existing alpha-whale
   Lightsail box as a co-tenant. Cost per project ≈ $3.50/mo (one
   third of the shared $10/mo plan; portfolio-humberto becomes the
   third tenant). No new AWS provisioning under TM-A5.
2. **LLM.** Swap the Anthropic-direct LangChain / Pydantic AI
   clients for AWS Bedrock cross-region inference profiles
   (`eu.anthropic.claude-sonnet-4-5-20250929-v1:0` +
   `eu.anthropic.claude-haiku-4-5-20251001-v1:0`) in eu-west-2. The
   Anthropic-direct path stays as a local-dev fallback when
   `BEDROCK_REGION` is unset.
3. **AWS auth on the box.** Lightsail does not natively support
   instance-attached IAM roles, so use a scoped IAM user
   (`tfl-monitor-bedrock`) with `bedrock:InvokeModel*` on the two
   model ARNs only. Access keys live in `/opt/tfl-monitor/.env`,
   `chmod 600`, owned by `ubuntu`.
4. **Service topology on the box.** Three long-running containers
   (`api`, `producers`, `consumers`). Airflow is **removed from
   production**: its scheduler + webserver consume ~700 MB of
   constant baseline RAM on a 1.9 GB host, which OOMs the box once
   tfl-monitor lands alongside alpha-whale. Periodic work (`dbt run`)
   becomes a host cron entry that shells into the api container.
   Airflow stays in the local dev compose for the portfolio narrative
   (DAG screenshots, ADR 003 history).
5. **Reverse proxy / TLS.** A single shared Caddy stack at
   `/opt/caddy/` on the host owns ports 80 + 443 and reverse-proxies
   to each tenant's `api` container by docker DNS name. Tenants
   declare a shared external network `caddy_net` in their compose
   files. TLS via Caddy + Let's Encrypt HTTP-01.
6. **DNS.** Cloudflare DNS only (gray cloud) — no proxy, no Origin
   Cert. The site block on the host's `Caddyfile` hard-codes
   `tfl-monitor-api.humbertolomeu.com`; the A record is created once
   by hand in the Cloudflare dashboard.
7. **IaC.** None. Manual provisioning per
   `alpha-whale/docs/deploy.md` is the canonical runbook. Terraform
   was rejected as ceremony for one box.
8. **CI/CD.** `.github/workflows/deploy.yml` rsyncs the working tree
   over SSH and runs `scripts/deploy.sh` on the box. Three GitHub
   secrets: `LIGHTSAIL_SSH_KEY` (private key), `LIGHTSAIL_HOST`
   (static IP), `LIGHTSAIL_HOST_KEY` (pinned `known_hosts` entry,
   closes the `ssh-keyscan` TOFU/MITM window). No GHA OIDC role —
   the deploy path doesn't need AWS API calls.
9. **Healthcheck on deploy.** Internal `docker exec curl
   http://localhost:8000/health` first (5 attempts) distinguishes a
   container crash from a Caddy/DNS issue, followed by an external
   curl against the public hostname (3 attempts). Failing the
   external check after the internal passes warns "check DNS /
   Caddy".
10. **Operational safety.** 2 GB swap file (`/swapfile`,
    `swappiness=10`) added to the box as a paliative against
    transient memory pressure. CloudWatch billing alarm at $20/mo
    on the shared AWS account.

## Consequences

- **Pros**
  - Steady-state cost lands at ~$5.60/mo (Lightsail share $3.50 +
    Bedrock ~$2). $100 AWS credit covers ~18 months across the
    shared account's three tenants.
  - Zero new AWS infra under TM-A5. Provisioning surface area is one
    `/opt/tfl-monitor/` directory + one Cloudflare A record + one
    appended site block in `/opt/caddy/Caddyfile`.
  - Shared Caddy is the multi-tenant abstraction every other
    free-hosting community converges on (nginx-proxy, Traefik,
    Caddy-Docker-Proxy). Adding a fourth tenant is one site block.
  - Bedrock cross-region inference profiles isolate us from
    per-region model availability changes; the Anthropic-direct path
    survives as a dev escape hatch.
  - GHA SSH deploy with pinned host key is the simplest pattern that
    keeps the keyscan TOFU window closed.

- **Cons**
  - Single instance, single AZ. Lightsail snapshot is the only
    recovery story; a host outage takes both tenants down.
  - Airflow is dev-only. Operators wanting a DAG visualisation in
    production must SSH in and re-create the daemons by hand, which
    we accept because the production work — periodic `dbt run` — is
    a single cron entry.
  - Scoped IAM user with keys in `.env` is weaker than an instance
    role. Mitigated by repo-level secret hygiene + scoped action
    policy (`bedrock:InvokeModel*` on the two model ARNs only).
  - Cross-repo coupling: any host-level Caddy change touches both
    repos (alpha-whale ships the in-stack-caddy removal, tfl-monitor
    ships its own site block snippet).

## Supersedes

- [ADR 003 — Airflow on Railway](./003-airflow-on-railway.md) is
  marked **superseded** by this ADR. Railway is no longer in the
  hosting matrix; the Airflow deployment that justified ADR 003 is
  removed from production.

## References

- `.claude/specs/TM-A5-plan.md` — full Phase-2 plan (decisions,
  runbook, credentials, risks)
- `alpha-whale/docs/deploy.md` — canonical Lightsail provisioning
  runbook
- PR #67 (plan pivot), #68 (Bedrock swap), #16 alpha-whale (shared
  Caddy), #69 (deploy infra)
