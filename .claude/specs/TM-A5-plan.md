# TM-A5 — Plan (Phase 2, revised 2026-05-14)

Implementation plan for **TM-A5: Bedrock LLM swap + deploy to shared
Lightsail box**. Built from `.claude/specs/TM-A5-research.md`, the
2026-04-29 budget reset, and a live inspection of the shared box on
2026-05-14. Supersedes both the original "all-AWS Fargate pivot" and
the interim "EC2 spot + DuckDNS" reading.

## 1. Charter (locked)

Deploy tfl-monitor onto the **existing shared AWS Lightsail box**
(eu-west-2, $10/mo plan, 2 GB RAM, Ubuntu 24.04, amd64) that already
hosts `alpha-whale`. Swap the Anthropic-direct LLM client for **AWS
Bedrock** (Claude Sonnet 4.5 + Haiku 4.5 via EU cross-region inference
profiles). Replace Airflow with **host-level cron** in production to
fit the box's RAM envelope. Keep every other tier on its existing
free plan.

| Layer | Host | Cost (this project's share) |
|---|---|---|
| Backend compute (FastAPI + ingestion producers + consumers) | Shared AWS Lightsail (eu-west-2), existing instance | ~$3.50/mo (1/3 of $10) |
| LLM (Sonnet 4.5 + Haiku 4.5) | AWS Bedrock (eu-west-2 cross-region inference) | ~$2/mo at portfolio traffic |
| Periodic jobs (dbt builds, RAG re-ingestion) | Host `cron` on the box, invoking `docker exec` | $0 |
| Postgres warehouse + (now-removed) Airflow metadata | Supabase free | $0 |
| Kafka broker | Redpanda Cloud Serverless free | $0 |
| Frontend | Vercel free hobby (`tfl-monitor.vercel.app` + `tfl-monitor.humbertolomeu.com`) | $0 (TM-E4 already done) |
| Vector DB | Pinecone serverless free | $0 |
| Backend HTTPS | Caddy + Let's Encrypt (HTTP-01) on the shared box | $0 |
| DNS | Cloudflare (`humbertolomeu.com` zone, DNS only / gray cloud) | $0 |
| Image registry | GHCR (GitHub free) | $0 |
| Observability | Logfire + LangSmith free tiers | $0 |

**Steady-state target: ~$5.50/mo effective for tfl-monitor**
(~$3.50 Lightsail share + ~$2 Bedrock). $100 AWS credit covers
~18 months at this run-rate.

ADR 003 (Airflow on Railway) becomes superseded by ADR 006 (Bedrock +
shared Lightsail + Caddy multi-tenant + cron-not-Airflow), committed
in the final PR.

### Files added

```
infra/
├── docker-compose.prod.yml  # 3 services: api, producers, consumers
├── caddyfile.snippet        # site block to merge into /opt/caddy/Caddyfile
├── cron.d/tfl-monitor       # host cron entries for dbt + periodic jobs
├── .env.example             # production env-var template
└── README.md                # provisioning + deploy + ops runbook

scripts/
├── bootstrap-tenant.sh      # one-shot: clone repo into /opt/tfl-monitor, build images
├── deploy.sh                # idempotent redeploy: pull + up + healthcheck
└── cron-dbt-run.sh          # cron entry-point: invokes dbt inside api container, logs+spans

src/api/Dockerfile           # API-only image (split from ingestion), amd64
src/ingestion/run_producers.py   # collapses 3 producers in one process
src/ingestion/run_consumers.py   # collapses 3 consumers in one process

.github/workflows/deploy.yml # on main push: rsync + ssh + compose up

.claude/adrs/006-aws-deploy.md  # ADR text in PR-3
```

### Files modified

```
src/api/agent/graph.py            # ChatAnthropic -> ChatBedrockConverse
src/api/agent/extraction.py       # pydantic-ai "anthropic:..." -> "bedrock:..."
pyproject.toml                    # +langchain-aws, +boto3
uv.lock                           # regenerated
.env.example                      # remove ANTHROPIC_API_KEY (kept commented for dev), add AWS_REGION + BEDROCK_*_MODEL_ID
docker-compose.yml                # local dev keeps anthropic + Airflow for portfolio demo
src/ingestion/Dockerfile          # amd64 base, slim
ARCHITECTURE.md                   # deployment table -> shared Lightsail + Bedrock + Supabase + Redpanda Cloud + Vercel
README.md                         # deploy section + cost table + ops link
PROGRESS.md                       # TM-A3, TM-A4, TM-A5 -> done
.claude/adrs/003-airflow-on-railway.md  # status: superseded by 006
.gitignore                        # .env (already covered), /opt-style mounts
```

### Untouched

`contracts/openapi.yaml`, `contracts/schemas/*`, `contracts/sql/*`,
`dbt/`, `web/lib`, `web/components`, `web/app`, `src/api/db.py`,
`src/api/schemas.py`, `src/api/main.py` (CORS allowlist already
covers the Vercel URL), `src/rag/`, `tests/` (unit tests pick up
Bedrock via env-var swap; no test code changes).

### Cross-repo touch: alpha-whale

PR-2 ships a **separate small PR in `alpha-whale`** removing its
in-stack Caddy and joining the new shared `caddy_net`. See §3
"Prerequisite: alpha-whale refactor".

### PR sequence (3 PRs in tfl-monitor + 1 in alpha-whale)

| # | Repo | Branch | Tracks touched | Approx LoC |
|---|---|---|---|---|
| **PR-A** | alpha-whale | `chore/shared-caddy-tenant` | infra | ~30 |
| **PR-1** | tfl-monitor | `feature/TM-A5-bedrock-swap` | D-api-agent (`src/api/agent/`) + B-ingestion (`src/ingestion/run_*.py`) — declared cross-track | ~200 source + 80 test |
| **PR-2** | tfl-monitor | `feature/TM-A5-aws-deploy` | A-infra (`infra/`, `scripts/`, Dockerfile, `.github/workflows/`) | ~300 |
| **PR-3** | tfl-monitor | `feature/TM-A5-adr-progress` | meta (`.claude/adrs/`, `ARCHITECTURE.md`, `README.md`, `PROGRESS.md`) | ~250 markdown |

PR-1 declares the cross-track touch in its body (D + B) under ADR 002
"Consequences" wording: the Bedrock swap is API-owned and the
collapse is mechanical — no contract change. Sibling WPs are
absorbed: TM-A3 ("create Supabase project + paste credential"),
TM-A4 ("create Redpanda cluster + paste creds"). TM-E4 is already
done (Vercel live).

## 2. Decisions (Phase 2 lock, revised)

| # | Question | Decision |
|---|---|---|
| 1 | Compute platform | **Shared existing AWS Lightsail** in eu-west-2, $10/mo plan (2 GB RAM, 1 vCPU, 60 GB SSD, 3 TB transfer), Ubuntu 24.04 LTS, amd64. No provisioning needed. |
| 2 | OS / runtime | **Already provisioned.** Box has Docker + Docker Compose v2 + Caddy. New tenant only adds `/opt/tfl-monitor/` directory and joins the shared network. |
| 3 | Service topology on the box | **3 long-running services** (down from 5): `api`, `producers`, `consumers`. Airflow webserver + scheduler removed. Defined in `infra/docker-compose.prod.yml`. |
| 4 | Service collapse | **6 ingestion daemons -> 2 processes**: `run_producers.py` runs `LineStatusProducer().run_forever()` + `ArrivalsProducer().run_forever()` + `DisruptionsProducer().run_forever()` under one `asyncio.gather`; `run_consumers.py` mirrors for the three consumers. Existing classes unchanged; entry-point is new. |
| 5 | LLM provider | **Bedrock for prod, Anthropic-direct stays as opt-in for local dev** (`docker-compose.yml` keeps `ANTHROPIC_API_KEY` for the dev developer who has it). Selection by env: when `BEDROCK_REGION` is set, use Bedrock; else fall back to Anthropic-direct. Default `.env.example` flips to Bedrock. |
| 6 | LangChain Bedrock client | **`langchain-aws.ChatBedrockConverse`** (Bedrock Converse API, native tool-calling). `ChatAnthropic` import stays as a fallback path gated by env. |
| 7 | Pydantic AI Bedrock | **`pydantic-ai >=1.85` model string `"bedrock:eu.anthropic.claude-haiku-4-5-20251001-v1:0"`** (cross-region inference profile, eu-west-2 entry). Fits the `pydantic-ai>=1.75` line in `pyproject.toml` from TM-D5. |
| 8 | AWS auth on the box | **Scoped IAM user** with access keys in `/opt/tfl-monitor/.env` (chmod 600). Permissions: `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` on the two model ARNs only. Lightsail does not support instance-attached IAM roles natively — IAM user is the canonical pattern. |
| 9 | AWS auth in CI | **None.** GHA does not call AWS directly. Deploy uses SSH (see #11). If integration tests need Bedrock in CI, add OIDC role later via TM-F follow-up — out of scope here. |
| 10 | Image registry | **None for prod.** Images build on the box via rsync of source + `docker compose up -d --build` (matches alpha-whale pattern). GHCR push deferred — adds complexity without portfolio value for a single-tenant deploy. |
| 11 | Deploy mechanism | **GHA workflow over SSH** using `webfactory/ssh-agent@v0.9.0` + GitHub secrets `LIGHTSAIL_SSH_KEY` (private key contents) + `LIGHTSAIL_HOST` (static IP). Workflow rsyncs the working tree, then `docker compose up -d --build` over SSH. Reuses alpha-whale's documented pattern. |
| 12 | Reverse proxy / TLS | **Shared Caddy + Let's Encrypt (HTTP-01)**. Caddy lives in its own `/opt/caddy/` stack (refactored out of alpha-whale's compose — see §3 Prerequisite). One Caddyfile, one site block per tenant. Cloudflare DNS only (gray cloud), no proxy. |
| 13 | Caddy multi-tenant pattern | **Shared external docker network `caddy_net`**. Central Caddy joins it. Each tenant's compose stack declares `caddy_net` as `external: true` and routes its `api` (or equivalent edge service) into the network. Caddy reverse-proxies by docker DNS name `tfl-monitor-api:8000`. |
| 14 | DNS | **Cloudflare A record manually in dashboard** for `tfl-monitor-api.humbertolomeu.com` -> `13.41.145.33` (static IP). Gray cloud (DNS only). No Cloudflare proxy, no Origin Cert. No Terraform. |
| 15 | Image arch | **amd64-only.** Box is amd64. All images already build under amd64 on the author's M-series laptop via `--platform=linux/amd64`. |
| 16 | API + ingestion image split | **Yes** — new `src/api/Dockerfile` produces `tfl-monitor-api`. Faster API rebuilds, ~250 MB image. Ingestion image stays in `src/ingestion/Dockerfile`. |
| 17 | Airflow | **Removed from prod.** Host cron + `docker exec` for dbt builds. Airflow stays in `docker-compose.yml` for local dev (portfolio demo + screenshots). Decision driven by RAM math: Airflow scheduler + webserver hold ~700 MB constant on a 1.9 GB shared box. See ADR 006. |
| 18 | Periodic jobs in prod | **Host cron** in `/etc/cron.d/tfl-monitor`. Entries call `scripts/cron-dbt-run.sh` which does `docker exec tfl-monitor-api-1 uv run dbt run --profiles-dir ... --project-dir ...`. Output redirected to `/opt/tfl-monitor/cron.log` (owned by `ubuntu`, so the cron user has write access — `/var/log/` is root-owned and would fail silently). Logfire tracing happens inside the api container's existing Logfire init; no extra wrapper at the cron level. |
| 19 | Secrets management | **Plain `/opt/tfl-monitor/.env` file**, chmod 600, owned by `ubuntu`. Populated by the author once via scp from the workstation. No Secrets Manager / Parameter Store. |
| 20 | RDS / RDS Proxy | **None.** Supabase remains the warehouse. Airflow metadata schema dropped (no Airflow in prod). |
| 21 | Custom domain | **Yes — used in TM-A5.** `tfl-monitor-api.humbertolomeu.com` via Cloudflare DNS. Replaces the original "DuckDNS for v1, custom in TM-F1" plan. |
| 22 | CloudWatch billing alarm | **Already active** on the shared AWS account (confirmed 2026-05-14). Covers tfl-monitor + alpha-whale + future tenants. SNS -> email. |
| 23 | CloudWatch logs | **Skipped.** Container stdout stays in docker on the box; `docker compose logs -f api` is the operator surface. Long-term observability is Logfire. |
| 24 | Auto-scaling / DR | **None.** Single instance, single AZ. Lightsail snapshot before any plan change. |
| 25 | Bedrock model access | **Already approved** in the shared AWS account for Sonnet 4.5 + Haiku 4.5 in eu-west-2 (confirmed by author 2026-05-14). |
| 26 | Swap on the box | **2 GB swap file at `/swapfile`** with `swappiness=10`. Already applied 2026-05-14. Persisted via `/etc/fstab` + `/etc/sysctl.d/99-swap.conf`. |

### Cost lock (steady-state, this project's share)

| Line | $/mo |
|---|---|
| Lightsail share (1/3 of $10/mo plan) | ~3.50 |
| Bedrock (50 chat sessions × 5 turns × ~1500 tokens × Sonnet 4.5 + Haiku 4.5) | ~2.00 |
| Bandwidth (1 GB egress/mo at portfolio traffic) | ~0.10 |
| Supabase free | 0 |
| Redpanda Cloud Serverless free | 0 |
| Vercel hobby free | 0 |
| Pinecone serverless free | 0 |
| Cloudflare DNS free | 0 |
| Logfire + LangSmith free | 0 |
| **Total** | **~$5.60/mo** |

$100 AWS credit / 3 projects × 18 months = ~$1.85/project/month
ceiling -> fits with margin. CloudWatch billing alarm fires at
$20/mo across the whole account as the safety net.

## 3. Provisioning runbook (Phase 3)

Everything below runs in this order. Each step has an exit check.
**If reality diverges from this plan in any step, stop and report:**
*"Expected: X. Found: Y. How should I proceed?"*

### Step 0 — Prerequisites on the author's laptop

| Tool | Why | Verify |
|---|---|---|
| AWS account credentials | IAM user creation in §3.2 | `aws sts get-caller-identity` (region irrelevant for IAM) |
| Cloudflare dashboard access | DNS A record creation in §3.4.6 | https://dash.cloudflare.com -> humbertolomeu.com zone visible |
| SSH key `/Users/humbertolomeu/.ssh/alpha-whale-lightsail.pem` | SSH into the box | `ssh ubuntu@13.41.145.33 'whoami'` returns `ubuntu` |
| `gh` CLI authenticated | PR creation, secret upload | `gh auth status` |

Exit check: all four green.

### Prerequisite — alpha-whale refactor (PR-A)

Before any tfl-monitor compose lands, alpha-whale must release its
in-stack Caddy so the shared Caddy can take over the host's :443.

**In the alpha-whale repo, branch `chore/shared-caddy-tenant`:**

1. Delete `Caddyfile` from the repo (content moves to the shared
   Caddyfile on the box — see Step 1 below).
2. Edit `docker-compose.yml`:
   - Remove the `caddy:` service block (lines 14-28 in the inspected
     version).
   - Remove the `caddy_data` and `caddy_config` named volumes.
   - Add a top-level `networks:` block declaring `caddy_net` as
     `external: true`.
   - On the `api:` service, add `caddy_net` to its `networks:` list
     (alongside its existing default network).
3. Update `docs/deploy.md`:
   - §2 "First deploy" loses the Caddy build step (Caddy is
     pre-existing on the box).
   - Add a §2.5 "Shared Caddy" pointer: "The host's `/opt/caddy/`
     stack owns ports 80/443 and routes to each tenant by docker
     DNS name. See `tfl-monitor` repo TM-A5 plan for the shared
     Caddyfile pattern."
   - §3 DNS table unchanged (still `api.<domain>` -> static IP).
4. Open PR-A. Merge **before** PR-2.

Exit check: `docker compose -f /opt/alpha-whale/docker-compose.yml
config` parses without the `caddy` service and lists `caddy_net` as
`external: true`.

### Step 1 — Shared Caddy stack on the box (one-time, ~10 min)

Done on the box, not in git initially. Files synced from the
tfl-monitor repo's `infra/caddyfile.snippet` later for the
tfl-monitor portion.

```bash
ssh ubuntu@13.41.145.33

sudo mkdir -p /opt/caddy
sudo chown ubuntu:ubuntu /opt/caddy
cd /opt/caddy

# docker network for routing
docker network create caddy_net

# /opt/caddy/Caddyfile
cat > Caddyfile <<'EOF'
{
        email letsencrypt@humbertolomeu.com
}

(scanner_block) {
        @scanner path /wp-* /wp-admin* /wp-content* /wp-includes* /wp-login.php /wp-json* /xmlrpc.php /.env* /.git* /.aws* /.ssh* /admin* /administrator* /phpmyadmin* /pma* /myadmin* /cgi-bin/* /shell.php /cmd.php /eval.php /backdoor.php /vendor/phpunit* /vendor/laravel* /.DS_Store /dump.sql /backup.sql /database.sql /backup.zip /sftp-config.json /web.config /server-status /owa* /exchange*
        respond @scanner 403
}

alpha-whale.humbertolomeu.com {
        import scanner_block
        encode zstd gzip
        reverse_proxy alpha-whale-api-1:8000
        log {
                output stdout
                format json
        }
}

tfl-monitor-api.humbertolomeu.com {
        import scanner_block
        encode zstd gzip
        reverse_proxy tfl-monitor-api-1:8000
        log {
                output stdout
                format json
        }
}
EOF

# /opt/caddy/docker-compose.yml
cat > docker-compose.yml <<'EOF'
services:
  caddy:
    image: caddy:2-alpine
    container_name: shared-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - caddy_net

networks:
  caddy_net:
    external: true

volumes:
  caddy_data:
  caddy_config:
EOF
```

Exit check: `caddy_net` exists in `docker network ls`; Caddyfile
parses (run `docker compose config`).

**Cutover for alpha-whale (one-time, ~5 min downtime):**

```bash
cd /opt/alpha-whale
docker compose down  # drops the old in-stack caddy

git pull  # pulls the PR-A changes (network external etc.)
docker compose up -d  # api joins caddy_net

cd /opt/caddy
docker compose up -d  # shared caddy starts, claims :80/:443

# verify
curl -sI https://alpha-whale.humbertolomeu.com/health  # 200 expected
```

Exit check: `alpha-whale.humbertolomeu.com` still serves over HTTPS
with a valid Let's Encrypt cert; alpha-whale `/health` returns 200.

### Step 2 — Bedrock IAM user (one-time, ~5 min)

In the AWS Console -> IAM -> Users -> Create user:

1. Name: `tfl-monitor-bedrock`
2. Attach policy (inline JSON):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:eu-west-2::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:eu-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:eu-west-2:*:inference-profile/eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:eu-west-2:*:inference-profile/eu.anthropic.claude-haiku-4-5-20251001-v1:0"
      ]
    }
  ]
}
```

3. Create access key (Use case: "Application running outside AWS").
   Save `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` for §4.

Exit check: `aws sts get-caller-identity --profile tfl-monitor-bedrock`
returns the user ARN.

### Step 3 — PR-1: Bedrock swap + service collapse

Inside the tfl-monitor repo, branch `feature/TM-A5-bedrock-swap`.

#### 3.1 Bedrock LLM swap (`src/api/agent/`)

- `graph.py`: replace `ChatAnthropic` import with
  `langchain_aws.ChatBedrockConverse`. Add env-driven selector:
  `if os.environ.get("BEDROCK_REGION"): llm = ChatBedrockConverse(...)
  else: llm = ChatAnthropic(...)`. Model IDs from env
  (`BEDROCK_SONNET_MODEL_ID`, `BEDROCK_HAIKU_MODEL_ID`).
- `extraction.py`: pydantic-ai model string driven by env. If
  `BEDROCK_REGION` set -> `"bedrock:" + os.environ["BEDROCK_HAIKU_MODEL_ID"]`,
  else `"anthropic:claude-haiku-..."`.
- `pyproject.toml`: add `langchain-aws>=0.2` and `boto3>=1.35` to the
  main `[project].dependencies` list. Anthropic stays as transitive
  (LangChain still depends on it for the fallback path).
- `pyproject.toml`: move `dbt-core>=1.9` and `dbt-postgres>=1.9` out
  of `[dependency-groups].dev` into a new
  `[dependency-groups].dbt` group. The production `src/api/Dockerfile`
  installs both `main` and `dbt` groups (`uv sync --frozen --no-dev
  --group dbt --no-install-project`) so that `docker exec api uv run
  dbt run` from the host cron entrypoint resolves successfully. The
  local dev `docker-compose.yml` keeps Airflow which calls `dbt run`
  itself; both paths converge on the same group.

#### 3.1.5 API Dockerfile (`src/api/Dockerfile`)

Split out of `src/ingestion/Dockerfile`. Key differences from the
ingestion image:

- `RUN apt-get update && apt-get install --no-install-recommends -y curl && rm -rf /var/lib/apt/lists/*` so the healthcheck (`HEALTHCHECK`/compose-level) can shell out to curl. `python:3.12-slim` ships without curl.
- `uv sync --frozen --no-dev --group dbt --no-install-project` includes the dbt deps for the cron-triggered `dbt run` exec.
- `CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]`. Same rationale as decision #4: container sets `PYTHONPATH=/app/src` (matches the existing ingestion Dockerfile), so module paths skip the `src.` prefix.

#### 3.2 Service collapse (`src/ingestion/`)

- `run_producers.py`: new file, imports the three producer classes
  and gathers them under `asyncio.gather(*[p.run_forever() for p in
  [LineStatusProducer(), ArrivalsProducer(), DisruptionsProducer()]])`.
  Single Logfire init at top.
- `run_consumers.py`: mirrors for the three consumers.
- `src/ingestion/Dockerfile`: bump to amd64 base, keep slim. ENTRYPOINT
  becomes overridable so docker-compose can target `run_producers.py`
  or `run_consumers.py` per service.

#### 3.3 Acceptance — PR-1

- [ ] `uv run task lint && uv run task test && uv run bandit -r src --severity-level high && make check` all green.
- [ ] At least one new unit test in `tests/agent/` parametrising the LLM backend (Anthropic vs Bedrock) via env var, asserting both code paths construct successfully.
- [ ] PR body declares cross-track touch (D + B) under ADR 002.
- [ ] No deploy yet — image build is local-only.

### Step 4 — PR-2: compose stack + Caddy snippet + GHA deploy

Inside the tfl-monitor repo, branch `feature/TM-A5-aws-deploy`.

#### 4.1 Production compose (`infra/docker-compose.prod.yml`)

```yaml
services:
  api:
    build:
      context: ..
      dockerfile: src/api/Dockerfile
    container_name: tfl-monitor-api-1
    restart: unless-stopped
    env_file: ../.env
    networks:
      - caddy_net
      - tfl-monitor
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  producers:
    build:
      context: ..
      dockerfile: src/ingestion/Dockerfile
    container_name: tfl-monitor-producers-1
    restart: unless-stopped
    env_file: ../.env
    command: ["uv", "run", "python", "-m", "ingestion.run_producers"]
    networks:
      - tfl-monitor

  consumers:
    build:
      context: ..
      dockerfile: src/ingestion/Dockerfile
    container_name: tfl-monitor-consumers-1
    restart: unless-stopped
    env_file: ../.env
    command: ["uv", "run", "python", "-m", "ingestion.run_consumers"]
    networks:
      - tfl-monitor

networks:
  caddy_net:
    external: true
  tfl-monitor:
    driver: bridge
```

#### 4.2 Caddy snippet (`infra/caddyfile.snippet`)

For documentation. Already pre-included in `/opt/caddy/Caddyfile`
during Step 1, but the snippet lives in the repo so anyone re-creating
the box can copy it:

```caddyfile
tfl-monitor-api.humbertolomeu.com {
        import scanner_block
        encode zstd gzip
        reverse_proxy tfl-monitor-api-1:8000
        log {
                output stdout
                format json
        }
}
```

#### 4.3 Host cron (`infra/cron.d/tfl-monitor`)

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

0 */6 * * * ubuntu /opt/tfl-monitor/scripts/cron-dbt-run.sh >> /opt/tfl-monitor/cron.log 2>&1
```

`scripts/cron-dbt-run.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/tfl-monitor
docker exec tfl-monitor-api-1 uv run dbt run \
  --profiles-dir /app/dbt \
  --project-dir /app/dbt
```

#### 4.4 GHA workflow (`.github/workflows/deploy.yml`)

```yaml
name: Deploy
on:
  push:
    branches: [main]
    paths-ignore:
      - '**.md'
      - 'web/**'
      - '.claude/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup SSH agent
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.LIGHTSAIL_SSH_KEY }}

      - name: Trust host (pinned)
        run: |
          mkdir -p ~/.ssh
          chmod 700 ~/.ssh
          # Pinned host key — avoid TOFU/MITM. Capture once locally with
          #   ssh-keyscan -H 13.41.145.33 | grep -v '^#'
          # then paste output into GitHub secret LIGHTSAIL_HOST_KEY.
          printf '%s\n' "${{ secrets.LIGHTSAIL_HOST_KEY }}" > ~/.ssh/known_hosts
          chmod 644 ~/.ssh/known_hosts

      - name: Rsync source
        run: |
          rsync -avz --delete \
            --exclude=.env --exclude=.env.* \
            --exclude=.git --exclude=node_modules --exclude=.venv --exclude=web \
            --exclude=tests --exclude=.claude \
            ./ ubuntu@${{ secrets.LIGHTSAIL_HOST }}:/opt/tfl-monitor/

      - name: Build + restart
        run: |
          ssh ubuntu@${{ secrets.LIGHTSAIL_HOST }} <<'EOF'
            set -euo pipefail
            cd /opt/tfl-monitor
            docker compose -f infra/docker-compose.prod.yml up -d --build
          EOF

      - name: Healthcheck
        run: |
          for i in 1 2 3 4 5; do
            if curl -sf https://tfl-monitor-api.humbertolomeu.com/health; then
              exit 0
            fi
            sleep 5
          done
          echo "Healthcheck failed after 5 retries" >&2
          exit 1
```

GitHub repo secrets (Settings -> Secrets and variables -> Actions):

- `LIGHTSAIL_SSH_KEY` — paste the entire `alpha-whale-lightsail.pem`
  contents (same key already used by alpha-whale's CI).
- `LIGHTSAIL_HOST` — `13.41.145.33`.
- `LIGHTSAIL_HOST_KEY` — output of `ssh-keyscan -H 13.41.145.33 | grep -v '^#'`
  captured once on the author's laptop. Pinning the host key
  eliminates the TOFU/MITM window that a runtime `ssh-keyscan` in CI
  would leave open.

#### 4.5 First-deploy sequence

```bash
ssh ubuntu@13.41.145.33

sudo mkdir -p /opt/tfl-monitor
sudo chown ubuntu:ubuntu /opt/tfl-monitor
cd /opt/tfl-monitor
```

```bash
rsync -avz --delete \
  --exclude=.env --exclude=.env.* \
  --exclude=.git --exclude=node_modules --exclude=.venv --exclude=web \
  --exclude=tests --exclude=.claude \
  ~/tfl-monitor/ ubuntu@13.41.145.33:/opt/tfl-monitor/

scp ~/tfl-monitor/.env.production ubuntu@13.41.145.33:/opt/tfl-monitor/.env
ssh ubuntu@13.41.145.33 'chmod 600 /opt/tfl-monitor/.env'

ssh ubuntu@13.41.145.33 'cd /opt/tfl-monitor && docker compose -f infra/docker-compose.prod.yml up -d --build'

ssh ubuntu@13.41.145.33 'sudo cp /opt/tfl-monitor/infra/cron.d/tfl-monitor /etc/cron.d/tfl-monitor && sudo chmod 644 /etc/cron.d/tfl-monitor'
```

#### 4.6 DNS (one-time, ~2 min, manual)

Cloudflare dashboard -> humbertolomeu.com -> DNS -> Records -> Add:

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| A | `tfl-monitor-api` | `13.41.145.33` | DNS only (gray cloud) | Auto |

Exit check: `dig +short tfl-monitor-api.humbertolomeu.com` returns
`13.41.145.33` within ~30 seconds.

#### 4.7 Acceptance — PR-2

- [ ] Healthcheck endpoint returns 200 via Caddy + LE cert.
- [ ] `docker exec tfl-monitor-producers-1 ps aux | head` shows the three producer asyncio tasks running.
- [ ] Cron entry installed: `sudo cat /etc/cron.d/tfl-monitor`.
- [ ] GHA deploy workflow runs green on a no-op push.
- [ ] Memory after deploy: `free -m` shows ~500 MB free + swap headroom.
- [ ] Logfire ingesting traces from the api container.
- [ ] LangSmith ingesting traces from a test chat session.

### Step 5 — PR-3: ADR 006 + docs

Branch `feature/TM-A5-adr-progress`.

- `.claude/adrs/006-aws-deploy.md`: context, decision, consequences.
  Covers: shared Lightsail eu-west-2, Bedrock Claude 4.5 EU
  cross-region inference, Caddy multi-tenant shared stack, scoped
  IAM user (no instance role), no Terraform, host cron not Airflow.
  Documents the deviation from the original spot+ASG+DuckDNS plan
  and why (RAM math, cost lock, alpha-whale pattern reuse).
- `.claude/adrs/003-airflow-on-railway.md`: header status changes
  to `Superseded by 006`.
- `ARCHITECTURE.md`: deployment table updated.
- `README.md`: deploy section, cost table, ops link.
- `PROGRESS.md`: TM-A3, TM-A4, TM-A5 -> done with date.

#### Acceptance — PR-3

- [ ] All five doc files updated.
- [ ] PR title `docs(arch): TM-A5 ADR 006 + Lightsail deploy progress`.

## 4. Credentials reference table

Author needs to gather these before Step 4.5. **Bold = secret, do not
commit. Plain = config, OK in `.env.example`.**

| Var | Type | Where it comes from | Notes |
|---|---|---|---|
| `TFL_APP_KEY` | **secret** | TfL Unified API portal (already obtained) | Used by ingestion producers |
| `DATABASE_URL` | **secret** | Supabase project -> Settings -> Database -> Connection string (URI mode) | Includes user, password, host, port, db |
| `KAFKA_BOOTSTRAP_SERVERS` | config | Redpanda Cloud cluster overview | `<cluster>.<region>.redpanda.com:9092` |
| `KAFKA_SECURITY_PROTOCOL` | config | static | `SASL_SSL` |
| `KAFKA_SASL_MECHANISM` | config | static | `SCRAM-SHA-256` |
| `KAFKA_SASL_USERNAME` | **secret** | Redpanda Cloud -> Service accounts | |
| `KAFKA_SASL_PASSWORD` | **secret** | Redpanda Cloud -> Service accounts | |
| `OPENAI_API_KEY` | **secret** | OpenAI dashboard -> API keys | Used by RAG embedder + LlamaIndex query embedder |
| `EMBEDDING_MODEL` | config | static | `text-embedding-3-small` |
| `PINECONE_API_KEY` | **secret** | Pinecone console -> API keys | |
| `PINECONE_INDEX` | config | static | `tfl-strategy-docs` |
| `AWS_ACCESS_KEY_ID` | **secret** | IAM user from §3.2 | Box-only, not in repo |
| `AWS_SECRET_ACCESS_KEY` | **secret** | IAM user from §3.2 | Box-only, not in repo |
| `AWS_REGION` | config | static | `eu-west-2` |
| `BEDROCK_REGION` | config | static | `eu-west-2` (presence enables Bedrock path in graph + extraction) |
| `BEDROCK_SONNET_MODEL_ID` | config | static | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `BEDROCK_HAIKU_MODEL_ID` | config | static | `eu.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `LOGFIRE_TOKEN` | **secret** | Logfire dashboard -> Tokens | |
| `LANGSMITH_TRACING` | config | static | `true` |
| `LANGSMITH_API_KEY` | **secret** | LangSmith -> Settings -> API keys | |
| `LANGSMITH_PROJECT` | config | static | `tfl-monitor` |
| `ENVIRONMENT` | config | static | `production` |
| `APP_VERSION` | config | static | `v1.0.0` (bump per release) |

**Removed from `.env.example` in PR-1:** `ANTHROPIC_API_KEY` (Bedrock
replaces it; kept commented as opt-in for local dev).

**Removed from this plan vs original:** `GHCR_PAT`, `DUCKDNS_TOKEN`,
`DUCKDNS_SUBDOMAIN`, `AWS_GHA_ROLE_ARN`, `AIRFLOW_*`. Not used.

**GitHub repo secrets** (Settings -> Secrets and variables -> Actions):

- `LIGHTSAIL_SSH_KEY` — contents of `~/.ssh/alpha-whale-lightsail.pem`
- `LIGHTSAIL_HOST` — `13.41.145.33`

## 5. What we are NOT doing

- ECS Fargate, EKS, App Runner — over-engineered for one shared box.
- EC2 spot + ASG — Lightsail flat-price beats it at portfolio scale.
- ALB / Route 53 — Caddy + Cloudflare handles HTTPS + DNS for $0.
- Multi-AZ — single AZ accepted; snapshot before plan changes is the recovery story.
- RDS — Supabase free covers warehouse.
- MSK / self-managed Redpanda — Redpanda Cloud Serverless free covers Kafka.
- Secrets Manager / SSM Parameter Store — plain `.env` chmod 600.
- CloudWatch dashboards / X-Ray / Container Insights — Logfire + LangSmith handle observability.
- DuckDNS / dynamic DNS — Lightsail static IP + manual Cloudflare A record.
- Auto-scaling — single instance is the design.
- Airflow in production — host cron + `docker exec` (see ADR 006).
- S3 remote logging — host volume + Logfire are enough.
- Terraform / IaC — manual provisioning per alpha-whale runbook.
- GHCR push — local build on the box at deploy time, simpler.
- AWS OIDC role for GHA — SSH key auth is sufficient for SSH deploy; OIDC reserved for future Bedrock-in-CI work.
- Multi-architecture image builds — amd64 only.
- Bedrock provisioned throughput — on-demand fits portfolio traffic.
- Bedrock guardrails / agents — `ChatBedrockConverse` direct invocation only.
- Anthropic-direct removal — kept as local-dev opt-in (decision #5).
- Migration off Pinecone / OpenAI / Logfire / LangSmith.
- Custom prompt-injection filter — same scope as TM-D5.
- Cloudflare proxy + Origin Cert — gray-cloud DNS only.
- Per-tenant Caddy — shared Caddy at `/opt/caddy/`.

## 6. Risks revisited

| Risk | Mitigation |
|---|---|
| Lightsail RAM saturation (1.9 GB shared) | Airflow removed (saves ~700 MB constant). Swap 2 GB applied (`swappiness=10`). Stack footprint without Airflow ~300 MB. |
| Bedrock model access denied or model deprecated | Step 2 verifies access. Fall back to Anthropic-direct via env (`unset BEDROCK_REGION`). |
| Bedrock Sonnet/Haiku 4.5 IDs change | Centralised in env vars; one-line swap when AWS updates the IDs. |
| `ChatBedrockConverse` tool-calling differs from Anthropic SDK | LangChain normalises; tests parametrise the env path so both backends pass the same suite. |
| Caddy cutover (alpha-whale -> shared) breaks alpha-whale HTTPS mid-cutover | Run cutover during off-hours; rollback is `docker compose up` of the old alpha-whale stack (5-min undo). |
| SSH key leak via GHA secret | Key is scoped to one Lightsail box; rotate by generating a new pair and updating both `~/.ssh/authorized_keys` on the box and the GHA secret. Repo-scoped secret minimises blast radius. |
| `.env` exposure on the box | chmod 600, owned by `ubuntu`. Box itself is the boundary. |
| Bedrock cost overrun | CloudWatch billing alarm at $20/mo on the shared account catches anything pathological. |
| Cloudflare DNS misconfiguration | Manual A-record creation is checked by `dig` in §3.4.6. Single record; one place to fix. |
| Lightsail snapshot/restore loss | Snapshot the box manually in the Lightsail console before any plan change or risky operation. Free up to one snapshot per instance. |
| Free-tier expiry on Supabase / Redpanda Cloud / Pinecone | All three free tiers are indefinite at portfolio scale. README documents the limits. |
| amd64-only images break ARM dev laptops | M-series Macs run amd64 via Rosetta with Docker Desktop; documented in `docker-compose.yml` comments. |

### Rollback

Three granularities:

1. **Per-deploy rollback.** `git revert <merge-sha>` on `main` then push -> GHA redeploys the previous tree. ~3 min.
2. **Per-PR rollback.** `git revert -m 1 <merge-sha>` for each of PR-1/PR-2/PR-3 individually. Bedrock swap revert restores Anthropic-direct path; `infra/` removal restores empty `/opt/tfl-monitor/` (manually drop the docker stack on the box).
3. **Whole-pivot rollback.** ADR 003 (Railway) preserved in git history with status `Superseded`. Worst case: re-revert to it.

## 7. Files expected to change (final)

Counts include both tests and source.

| Category | Added | Modified |
|---|---|---|
| Source | 4 (`run_producers.py`, `run_consumers.py`, `src/api/Dockerfile`, plus 1 compose file in `infra/`) | 3 (`graph.py`, `extraction.py`, `pyproject.toml` + `uv.lock`) |
| Caddy / Compose / scripts | 5 (`caddyfile.snippet`, `docker-compose.prod.yml`, `bootstrap-tenant.sh`, `deploy.sh`, `cron-dbt-run.sh`, `cron.d/tfl-monitor`) | 1 (`src/ingestion/Dockerfile` amd64 base) |
| CI/CD | 1 (`.github/workflows/deploy.yml`) | 0 |
| Tests | 2 (`tests/ingestion/test_run_*.py`, `tests/agent/test_bedrock_swap.py`) | 0 (existing agent tests parametrise) |
| Docs / ADR | 1 (`.claude/adrs/006-aws-deploy.md`) | 4 (`ARCHITECTURE.md`, `README.md`, `PROGRESS.md`, `.claude/adrs/003-airflow-on-railway.md`) |
| Configs | 1 (`infra/.env.example`) | 2 (`.env.example`, `.gitignore`) |
| **External (alpha-whale repo)** | 0 | 2 (`docker-compose.yml`, `docs/deploy.md`) — `Caddyfile` deleted |

Total ~21 new files in tfl-monitor, ~10 modified, plus 2 modified +
1 deleted in alpha-whale. ~700 LoC across all four PRs.

## 8. Confirmation gate

Before starting Phase 3, author confirms:

1. **Box state.** Inspection on 2026-05-14 confirms shared Lightsail at `13.41.145.33`, eu-west-2, 2 GB / amd64, alpha-whale already deployed. Swap 2 GB applied. Confirmed.
2. **Caddy multi-tenant pattern.** Option A — shared `/opt/caddy/` stack with external `caddy_net`. Cross-repo touch in alpha-whale required (PR-A). Confirmed.
3. **Airflow removal in prod.** Replaced by host cron + `docker exec`. Airflow stays in local dev compose for portfolio narrative. Confirmed.
4. **Subdomain.** `tfl-monitor-api.humbertolomeu.com` via Cloudflare DNS only (gray cloud). Confirmed.
5. **TLS.** Caddy + Let's Encrypt HTTP-01 on the shared box. No Cloudflare proxy, no Origin Cert. Confirmed.
6. **AWS auth.** Scoped IAM user with access keys in `.env` chmod 600. No instance role. Confirmed.
7. **Bedrock region + models.** `eu-west-2`, `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` + `eu.anthropic.claude-haiku-4-5-20251001-v1:0` cross-region inference profiles. Both already approved by account-level Bedrock access. Confirmed.
8. **Deploy mechanism.** GHA + SSH using `LIGHTSAIL_SSH_KEY` + `LIGHTSAIL_HOST` secrets. Local build on the box (no GHCR). Confirmed.
9. **CloudWatch billing alarm.** Already active on the shared AWS account (confirmed by author 2026-05-14). Covers the whole portfolio. Confirmed.
10. **Sequencing.** PR-A (alpha-whale refactor) -> PR-1 (Bedrock swap) -> PR-2 (deploy) -> PR-3 (ADR + docs). Confirmed.

Once confirmed, Phase 3 starts at §3 Step 0.
