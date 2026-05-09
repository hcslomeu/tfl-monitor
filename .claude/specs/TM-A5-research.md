# TM-A5 — Phase 1 research: AWS deploy pivot

Status: research (read-only)
Date: 2026-04-29
Supersedes (draft): ADR 003 — Airflow on Railway in production

## 1. Why this research

The original phase-7 plan deploys the backend to Railway, frontend to Vercel,
warehouse to Supabase, and Kafka to Redpanda Cloud Serverless. The author has
asked to pivot the production deployment to AWS. TM-A5 is the compute-side WP
for that pivot, but the decision cascades into TM-A3 (Postgres host), TM-A4
(Kafka host), and TM-E4 (frontend host). This document maps the AWS service
options for each impacted track, prices them at portfolio scale, and captures
open questions to resolve in Phase 2. No code or doc changes happen in Phase
1; the draft ADR at the end is intentionally not committed yet.

## 2. Inventory of what is being deployed

Pulled from `docker-compose.yml`, `pyproject.toml`, `airflow/`, `src/`, and
`.env.example`. Anything below has a real workload today; nothing is
speculative.

### 2.1 Container images

| Image source | Built from | Used by today | Runtime size (rough) |
|---|---|---|---|
| `python:3.12-slim` + `uv sync --no-dev` (`src/ingestion/Dockerfile`) | `pyproject.toml` + `src/` + `contracts/` | All ingestion producers and consumers, FastAPI (same image, different `command`) | ~400-500 MB |
| `apache/airflow:2.10.3` + `uv` (`airflow/Dockerfile`) | `airflow/requirements.txt` | Airflow webserver + scheduler + init | ~1 GB |
| `redpandadata/redpanda:v24.2.7` | upstream | Local broker, three topics | ~150 MB |
| `postgres:16` | upstream + init scripts in `contracts/sql/` | Local warehouse + Airflow metadata DB | ~500 MB |
| `redpandadata/console:v2.7.2` | upstream | Local UI only (profile `ui`) | n/a in prod |
| `minio/minio:RELEASE.2024-10-29T16-01-48Z` | upstream | Local only, no prod target | n/a in prod |

### 2.2 Long-running services that need a prod home

From `docker-compose.yml` and the API entrypoint:

1. **`tfl-line-status-producer`** — async daemon, polls TfL every 30 s,
   produces to topic `line-status`.
2. **`tfl-line-status-consumer`** — async daemon, consumes `line-status`,
   writes `raw.line_status`.
3. **`tfl-arrivals-producer`** — daemon, polls every 30 s, 5 NaPTAN hubs.
4. **`tfl-arrivals-consumer`** — daemon, writes `raw.arrivals`.
5. **`tfl-disruptions-producer`** — daemon, polls every 300 s, 4 modes.
6. **`tfl-disruptions-consumer`** — daemon, writes `raw.disruptions`.
7. **`tfl-monitor-api`** (the FastAPI process — currently absent from the
   compose file because TM-D2/D3 run it via `uv run` locally). HTTP service
   exposing `/api/v1/...` + the SSE chat endpoint, holds an
   `AsyncConnectionPool` and the compiled LangGraph agent in `app.state`.
8. **`airflow-webserver`** — HTTP UI on port 8080.
9. **`airflow-scheduler`** — long-running scheduler.
10. **`airflow-init`** — one-shot DB migration + admin user create. Must run
    once before webserver/scheduler.

Total long-running prod processes: 9. Plus one one-shot init.

### 2.3 Stateful dependencies

| Dependency | Schemas/topics in use | Local store | Prod store today |
|---|---|---|---|
| Postgres | `raw`, `ref`, `analytics`; Airflow's own metadata DB inside the same instance | `postgres-data` volume | Supabase free tier (planned) |
| Kafka | Topics `line-status`, `arrivals`, `disruptions` (1 partition, 1 replica) | `redpanda-data` volume | Redpanda Cloud Serverless free (planned) |
| Pinecone (vectors) | Index `tfl-strategy-docs`, three namespaces | n/a (always remote) | Pinecone serverless (already prod-only) |
| Object store | none in the prod plan; `minio` is local-only for parity drills | `minio-data` volume | n/a |

### 2.4 Secrets surface

From `.env.example`:

`TFL_APP_KEY`, `POSTGRES_*` (5), `KAFKA_BOOTSTRAP_SERVERS`,
`KAFKA_SECURITY_PROTOCOL`, `KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME`,
`KAFKA_SASL_PASSWORD`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`PINECONE_API_KEY`, `PINECONE_INDEX`, `EMBEDDING_MODEL`, `LANGSMITH_TRACING`,
`LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LOGFIRE_TOKEN`,
`AIRFLOW_ADMIN_USERNAME`, `AIRFLOW_ADMIN_PASSWORD`, `ENVIRONMENT`,
`APP_VERSION`. ≈ 24 variables. Of those, 11 carry actual secret material;
the rest are configuration.

### 2.5 Inbound traffic

- Public HTTPS to FastAPI (`/api/v1/*`, `/api/v1/chat/stream` is SSE — long-lived response).
- Public HTTPS to Airflow webserver (basic-auth gated). Lower traffic, internal use.
- Public HTTPS to Next.js (frontend; covered under TM-E4).
- Outbound HTTPS from every service to TfL Unified API (api.tfl.gov.uk),
  Anthropic, OpenAI, Pinecone, Logfire, LangSmith.

### 2.6 Cross-track entanglements

- ADR 003 deliberately collapsed Airflow's metadata DB onto the Supabase
  Postgres to keep one DB. That decision needs to ride along with TM-A3 if
  Postgres moves to RDS — Airflow will use the same RDS instance.
- TM-D5 added `analytics.chat_messages` (`contracts/sql/004_chat.sql`); the
  prod Postgres must run all four init scripts before the API starts.

## 3. Constraints inherited from CLAUDE.md and ARCHITECTURE.md

These narrow the design space; they are not up for debate in this WP:

1. **Tech stack is locked** without an ADR (CLAUDE.md §"Tech stack"). Moving
   off Anthropic Claude / Pinecone / dbt-core etc. is out of scope.
2. **Lean by default**. Hosted observability stays Logfire + LangSmith. No
   CloudWatch dashboards, no Grafana, no custom metrics pipeline (CLAUDE.md
   §"Principle #1" + §"Anti-patterns").
3. **One Postgres** for warehouse + Airflow metadata. Splitting them is a
   distinct ADR; default is "still one".
4. **Pydantic is the wire format** for everything; no migration to
   AWS-specific schema registries. Glue Schema Registry is explicitly out.
5. **Free tiers are preferred over paid tiers, but managed-by-AWS beats
   self-hosted-on-AWS for portfolio signal**. Author will trade some cost
   for "look, real AWS-managed services" provided the totals stay
   reasonable.

## 4. Per-track AWS option analysis

Pricing below uses `eu-west-2` (London) on-demand list price, April 2026.
Prices rounded to whole pounds where helpful. Free tier called out
explicitly.

### 4.1 TM-A3 — Postgres host

Today's plan: Supabase free tier (Postgres 15.x, 500 MB, pooler included).
This already runs on AWS underneath, but it is third-party-managed; the
pivot wants AWS-managed.

| Option | Monthly steady-state | Free-tier cover | Verdict |
|---|---|---|---|
| RDS PostgreSQL `db.t4g.micro` single-AZ, 20 GB gp3, 7-day backup | ~£12-15 (post-free-tier); free for first 12 months | 750 hr/mo `db.t2.micro`/`db.t3.micro`/`db.t4g.micro` + 20 GB storage + 20 GB backup, 12 months | **Primary recommendation.** Cheapest credible AWS-native Postgres. Engine = same Postgres 16 we use locally. |
| RDS PostgreSQL `db.t4g.small` single-AZ | ~£25 | partial only | Reach class — gives Airflow some headroom. Reconsider only if `db.t4g.micro` saturates. |
| Aurora Serverless v2, min 0.5 ACU | ~£44 floor + storage I/O | none | Over budget for portfolio. The autoscaling story is nice but unnecessary at this scale. |
| Aurora Serverless v2 with min 0 ACU (auto-pause) | floor drops, but cold-start hits SSE chat session | partial | Cold start latency hurts the agent demo; reject. |
| Postgres on EC2 (self-hosted) | ~£12 EC2 + EBS + ops time | none | Loses the "managed" portfolio signal that motivated the pivot. Rejected. |
| Stay on Supabase | £0 | yes, indefinite | Pragmatic carve-out, but contradicts the "all AWS" framing the author asked for. |

**Connection-pooling note.** Supabase ships PgBouncer; RDS does not. Two
options: (a) keep relying on the in-process `AsyncConnectionPool` (already
in `src/api/db.py:build_pool`, min 1 / max 4) and accept that producer +
consumer pods open one direct connection each — totals ≤ ~12 conns, well
inside `db.t4g.micro`'s default `max_connections=87`; or (b) front the
instance with RDS Proxy at ~£10-15/mo, which is wasteful at this scale.
**Recommend (a)**: it costs £0 and the conn-count budget fits.

**Backup posture.** RDS automated backups: 7 days, free up to the size of
the DB. No additional cost expected at < 5 GB used.

**TLS / connection string drift.** RDS hands back `postgres://USER:PASS@db-instance.xxxx.eu-west-2.rds.amazonaws.com:5432/DBNAME`. Local code reads
`DATABASE_URL` — already opaque to host shape. The init scripts in
`contracts/sql/` need to run once during provisioning; either via the EC2
bastion + `psql`, or via a one-off ECS task running `psql -f`. Decide in
Phase 2.

### 4.2 TM-A4 — Kafka host

Today's plan: Redpanda Cloud Serverless free tier. Kafka wire compatible,
`aiokafka` clients in `src/ingestion/*` are unaware of the broker brand.
ADR 001 is built on that property.

| Option | Monthly steady-state | Code change | Verdict |
|---|---|---|---|
| MSK Serverless | ~£430 floor (control-plane $0.75/hr) + per-partition + storage | none (`aiokafka` works) | **Eliminated.** Floor is 30× the rest of the stack. |
| MSK provisioned `kafka.t3.small`, 1 broker | ~£60-90 + EBS | none | Affordable but heavy for one developer's portfolio. Reach option only if author wants the MSK line on the CV. |
| Self-managed Redpanda single-node on EC2 `t4g.small` (`arm64`), 20 GB gp3 | ~£12 EC2 + ~£2 EBS = **~£14** | none (still Kafka wire) | **Primary recommendation.** Zero client churn. Single-node is fine for 3 topics × 1 partition × low volume. ADR 001 still holds. |
| Self-managed Apache Kafka (KRaft) on EC2 | ~£14 plus more ops | none | Higher operational ceremony than Redpanda for no benefit here. |
| Kinesis Data Streams (3 streams, on-demand) | ~£20-40 | **breaking** — rewrite producers/consumers off `aiokafka`, lose `event_id`/partition-key story | Forces a contract refactor across `src/ingestion/*` for marginal cost benefit. Rejected unless author specifically wants Kinesis as a portfolio item. |
| Hybrid: keep Redpanda Cloud Serverless, run only compute on AWS | £0 | none | Pragmatic fallback if EC2-as-broker feels like it dilutes the AWS pivot story. |

**Recommendation:** self-managed Redpanda on a dedicated `t4g.small`. Cost
is the lowest credible option, no client refactor, fits the project's "lean
by default" principle, and the broker is still Kafka-wire-compatible so a
later migration to MSK is straightforward. Document it as a follow-up to
ADR 001 (extending its rationale: if `dev-container` mode works locally,
the same image works as a single-node prod broker; we accept the
single-node SLA tradeoff for portfolio scale).

**Networking note.** This broker should sit in the same VPC as the
producers and consumers and the API. Putting it on a private subnet keeps
the bootstrap address internal. If we ever need external admin tooling
(e.g. local `rpk` for inspection) that goes through a bastion or AWS SSM
Session Manager.

### 4.3 TM-A5 — Compute (FastAPI + 6 ingestion daemons + Airflow)

This is the heart of the pivot. Three families to weigh: pure container
PaaS, container-on-managed-orchestrator, and "an EC2 with docker compose".

#### 4.3.1 Compute platforms

| Option | Strength | Cost at our scale (8 always-on tasks) | Notes |
|---|---|---|---|
| **ECS Fargate** (one task per service, 0.25 vCPU / 0.5 GB) | Serverless containers, no instance management, integrates cleanly with ALB / Secrets Manager / IAM | ~£8/mo per task (Fargate price = $0.04048/vCPU-hr + $0.004445/GB-hr) → 8 × £8 = **~£64-70/mo compute**, plus ALB ~£18, plus CloudWatch logs ~£3 | Strongest portfolio signal of any option. ALB is the hidden line item. SSE works on ALB; no special config besides idle timeout ≥ 60s. |
| **ECS on EC2** (one `t4g.medium` packing all 8 containers) | One bill, one instance to patch, control-plane is still ECS | ~£24/mo EC2 + EBS + ALB ~£18 = **~£45/mo** | Cheaper than Fargate, still uses ECS scheduling. Loses some Fargate magic; we manage AMI updates. |
| **App Runner** (HTTP services only) | Auto-scale, simplest deploy, built-in TLS | $0.064/vCPU-hr active + $0.007/GB-hr provisioned, plus per-request fees | Doesn't fit Airflow scheduler or pure-worker daemons (no inbound HTTP). Could host **only** FastAPI; rest still need ECS/EC2. Splits the platform — rejected unless we also drop the workers. |
| **Bare EC2 + docker compose** (`t4g.medium`, single host) | Mental model identical to local. Cheapest "real AWS" answer | ~£24/mo EC2 + £4 EBS + £0 (Caddy/Traefik for TLS) = **~£28/mo** | Weakest AWS-native signal. Strongest "I deployed it on AWS in an afternoon" answer. Operational story is `docker compose pull && up -d`. |
| **EKS** | Kubernetes credential | EKS control plane $73/mo + nodes | Over-engineered for nine containers. Rejected. |
| **AWS MWAA** (managed Airflow) | Removes Airflow ops | ~£295/mo for `mw1.small` | Eliminates the need to host Airflow ourselves but blows the budget. Rejected. |
| **Lambda + EventBridge** for ingestion polling | No always-on cost | Free tier covers it | Rewrite of the polling loops; loses Kafka producer continuity model. Rejected — TM-B2/B3 already shipped a daemon shape. |

#### 4.3.2 Networking pattern (cuts across all options)

The most expensive easy mistake: a NAT Gateway costs ~£26/mo per AZ just
for being on. We do not need one if every task that needs egress runs in a
public subnet with an auto-assigned public IP. Tradeoff: those tasks are
reachable from the internet on their security-group ports — fine because
we only open 443 on the ALB target group, and the tasks themselves only
listen on internal ports (Fargate awsvpc mode + SG = effective shield).

VPC plan (Phase 2 will pin this):

- One VPC, one AZ (eu-west-2a), one public subnet, one private subnet.
- Public subnet: ALB, broker EC2, ingestion tasks (with public IPs for
  egress), Airflow webserver task, NAT-less.
- Private subnet: RDS only.
- VPC endpoints (gateway type, free) for S3 and DynamoDB if anything ever
  needs them; interface endpoints for ECR/Secrets/Logs are ~£6/mo each, so
  default to public-IP egress instead.
- One security group per role: `sg-alb`, `sg-api`, `sg-worker`, `sg-broker`,
  `sg-rds`. RDS only accepts from `sg-api` + `sg-worker` + `sg-airflow`.

#### 4.3.3 Airflow deployment specifics

ADR 003's premise (Airflow + warehouse share a Postgres, LocalExecutor) is
not Railway-specific; it carries over. On AWS the cleanest mapping is two
ECS tasks (webserver + scheduler) sharing the same RDS instance. The
webserver sits behind the ALB on a separate target group; scheduler has no
inbound. The init container (DB migrate + admin user) becomes a one-shot
ECS task triggered by deploy.

**Storage.** Airflow logs: today they live in `airflow-logs` Docker
volume. On Fargate, ephemeral storage is wiped between task starts, so
logs need an off-task store. Three choices: (a) ship to CloudWatch Logs
(small volume, ~£0-3/mo for our usage); (b) S3 remote logging
(`AIRFLOW__LOGGING__REMOTE_LOGGING=True`, bucket on S3); (c) EFS mount.
**Recommend (b)**: it's the standard Airflow story, S3 cost is pennies,
and an `s3://tfl-monitor-airflow-logs/` bucket is one Terraform line.

**uv inside the Airflow image.** `airflow/Dockerfile` already installs
`uv`. The DAGs invoke `uv run dbt build` and `uv run python -m rag.ingest`
(per `airflow/dags/`). For that to work, the project source must be on
disk. Locally we bind-mount `./:/opt/tfl-monitor`. On Fargate there is no
host bind. Two options: (a) bake the project into the Airflow image at
build time (simpler, ~1.2 GB image but fine), (b) sync from S3 at task
boot. **Recommend (a)**: a multi-stage build ends with the project copied
into `/opt/tfl-monitor`, mirroring the local volume mount.

#### 4.3.4 Scaling posture

All ingestion services are single-instance daemons (consumer groups would
let us scale, but we have one partition each). Stay at desired-count = 1.
FastAPI: desired-count = 1, allow up to 2 only if the ALB shows sustained
saturation. Auto-scaling groups for ingestion are not warranted; auto-
scaling for FastAPI is optional.

**SSE compatibility.** ALB supports HTTP/1.1 chunked responses with no
buffering as long as the target sends headers promptly; FastAPI's
`sse_starlette.EventSourceResponse` already does. Set ALB idle timeout to
≥ 120 s so the ALB does not kill long-lived chat streams. (Default 60 s.)

#### 4.3.5 Recommendation

Two Phase-2 candidates, in cost order:

1. **Lean**: bare EC2 `t4g.medium` running docker compose, no ALB
   (Caddy/Traefik on the box terminates TLS, ACM optional). **~£28-32/mo**.
   Lowest cost, weaker AWS-native signal.
2. **Portfolio-native**: ECS Fargate behind ALB, RDS for Postgres,
   self-managed Redpanda on EC2 `t4g.small`, S3 remote logging, Secrets
   Manager. **~£100-110/mo all-in** (see §6).

The author's brief stresses "AWS pivot" which reads as "show real AWS",
so **the recommended Phase-2 entry point is the portfolio-native option**.
The lean option stays in the doc as a fallback if the budget tightens.

### 4.4 TM-E4 — Frontend host

| Option | Cost | SSR support | Verdict |
|---|---|---|---|
| **Amplify Hosting** | Free tier: 1000 build min/mo, 5 GB storage, 15 GB serve. After: ~£0-3/mo for portfolio traffic | Full Next.js 16 SSR via the Next.js compute adapter | **Primary recommendation.** Closest port from Vercel. AWS-native. |
| **Vercel (status quo)** | £0 hobby tier | full | Pragmatic carve-out. Choose only if Amplify's Next.js 16 support proves rough; the rest of phase 7 still holds. |
| **CloudFront + S3 static export** | Free tier covers it | none — TM-E1b/E2 are async server components, would need rewrite | Rejected. |
| **Lightsail** | ~£3/mo container | manual | No CDN free; reject. |
| **App Runner** | ~£8/mo + per-request | yes (Node container) | Possible but overkill for a low-traffic portfolio frontend. |

**Recommendation:** Amplify Hosting. Verify in Phase 2 that the Next.js 16
adapter handles our async server components and our `apiFetch` calls
through to the Fargate-backed API (CORS allow-list already includes
`https://tfl-monitor.vercel.app`; an Amplify URL needs adding to
`src/api/main.py` CORS list — TM-D1 acceptance criterion).

## 5. Cross-cutting infra

### 5.1 Image registry

- **ECR** (private). One repo per image: `tfl-monitor-ingestion`,
  `tfl-monitor-api`, `tfl-monitor-airflow`. ECR storage £0.10/GB-month, free
  500 MB-month. Expected: ~£0.50/mo.
- Alternative GHCR is free and works fine but Fargate pulling from a
  non-ECR registry costs an internet round-trip and slightly worse pull
  latency. ECR keeps the platform AWS-native.

### 5.2 Secrets

- **Secrets Manager**: $0.40/secret/mo + per-call. ≈ 11 real secrets ⇒
  ~£3.50/mo. Provides JSON-blob-per-secret, IAM-gated.
- **SSM Parameter Store** (Standard): free. SecureString supports
  KMS-encrypted secrets. Lower-friction, but Secrets Manager has tighter
  rotation and per-secret access logging.

**Recommendation:** Secrets Manager for the 11 actual secrets; Parameter
Store for the 13 pure config values. Costs ~£3.50/mo total. Tasks read at
boot via the AWS SDK (or Fargate's native `secrets` block in the task def
which injects them as env vars — preferred, no app code change).

### 5.3 IaC vs click-ops

Two routes:

- **Click-ops** the first deploy via the Console, capture every screen in
  a runbook. Faster to land, weaker for portfolio signal.
- **Terraform** (or AWS CDK) under `infra/terraform/`. Slower, but the
  resulting `infra/` folder is itself the strongest portfolio artefact in
  this entire WP — interviewers love `terraform plan` output that shows VPC
  + ECS + RDS + ALB + IAM in one tree.

**Recommendation:** Terraform under `infra/terraform/`, with a single
`main.tf`/module-per-concern split. Plain `terraform apply` from the laptop;
no remote state backend in S3 unless author wants the bonus exercise.
Bandit + ruff CI does not extend to `.tf` — leave Terraform-only linting
to a later WP if at all.

### 5.4 CI/CD

Today: GitHub Actions runs `make check`. Three new responsibilities:

1. Build and push images to ECR on `main`. Use OIDC federation
   (`aws-actions/configure-aws-credentials@v4`) so no long-lived AWS keys
   live in GitHub. Free.
2. Trigger an ECS service update with the new image tag. Either
   `aws ecs update-service --force-new-deployment` or `aws ecs
   register-task-definition` + `update-service`. ~30 lines of YAML.
3. (Optional) `terraform apply` on infra changes via a separate workflow,
   manually triggered.

This stays inside the GitHub Actions free tier for a public repo.

### 5.5 Observability

No change. Logfire and LangSmith remain the prod observability surface
(CLAUDE.md hard rule). What does change:

- **CloudWatch Logs** receives task stdout/stderr automatically when the
  Fargate `awslogs` driver is on. We do not build dashboards on top of it;
  it is purely a fallback when Logfire is down. Cost at ingest <
  1 GB/mo: ~£0-1/mo.
- **S3 remote logging for Airflow** as discussed in §4.3.3.

### 5.6 Domain + TLS

- One Route 53 hosted zone (~£0.40/mo) if author wants a custom domain
  (e.g. `tfl-monitor.lomeu.dev`). Otherwise the Amplify default and ALB
  default DNS work but read as less polished.
- ACM certificates are free for ALB and Amplify.

## 6. Cost summary scenarios

All in £/month, eu-west-2, post free tier (worst case after first 12 months
of RDS).

### 6.1 Scenario A — Lean (bare EC2 + docker compose, RDS, self-host Redpanda, Vercel frontend)

| Line | £/mo |
|---|---|
| EC2 `t4g.medium` (compute host) | 24 |
| EBS 20 GB gp3 (compute host) | 2 |
| RDS `db.t4g.micro` + 20 GB gp3 | 14 |
| EC2 `t4g.small` (Redpanda broker) | 12 |
| EBS 20 GB gp3 (broker) | 2 |
| ECR storage | 1 |
| Secrets Manager (11 secrets) | 4 |
| CloudWatch logs | 1 |
| S3 (Airflow logs + a little) | 1 |
| Frontend (Vercel) | 0 |
| **Total** | **~£61** |

In RDS free-tier window: subtract ~£14 → **~£47**.

### 6.2 Scenario B — Portfolio-native (Fargate + ALB, RDS, self-host Redpanda, Amplify frontend)

| Line | £/mo |
|---|---|
| Fargate, 8 tasks @ 0.25 vCPU / 0.5 GB always-on | 64 |
| ALB (HTTP + HTTPS, low LCU) | 18 |
| RDS `db.t4g.micro` + 20 GB gp3 | 14 |
| EC2 `t4g.small` (Redpanda broker) | 12 |
| EBS 20 GB gp3 (broker) | 2 |
| ECR storage | 1 |
| Secrets Manager (11 secrets) | 4 |
| CloudWatch logs | 3 |
| S3 (Airflow logs) | 1 |
| Amplify hosting | 0-3 |
| Route 53 hosted zone (optional) | 0.40 |
| **Total** | **~£120** |

In RDS free-tier window: subtract ~£14 → **~£106**.

### 6.3 Scenario C — All-AWS-managed (Fargate + ALB + RDS + MSK provisioned + Amplify)

| Line | £/mo |
|---|---|
| Fargate (same as B) | 64 |
| ALB | 18 |
| RDS `db.t4g.micro` | 14 |
| MSK provisioned `kafka.t3.small` × 1 broker + 20 GB EBS | 70 |
| ECR + Secrets + Logs + S3 + Amplify | 9-12 |
| **Total** | **~£175-180** |

Likely too steep for a personal portfolio unless the author actively wants
MSK on the CV.

### 6.4 Scenario D — Hybrid carve-outs (RDS + Fargate, but keep Redpanda Cloud + Vercel)

| Line | £/mo |
|---|---|
| Fargate + ALB + RDS + ECR + Secrets + Logs | 104 |
| Redpanda Cloud Serverless free | 0 |
| Vercel free | 0 |
| **Total** | **~£104** |

Cheaper than Scenario B and easier to operate (no broker to manage), but
the "all AWS" framing is weaker.

## 7. Open questions to resolve in Phase 2

1. **Scenario picking.** A vs B vs D. Default proposal: B. Confirm budget
   ceiling so Phase 2 can pin the IaC.
2. **Region.** `eu-west-2` (London) makes data-residency sense (TfL), and
   Amplify supports it. Confirm vs `eu-west-1` (Ireland) which is slightly
   cheaper on some line items.
3. **Custom domain.** If yes: which DNS registrar, which subdomain plan.
4. **Terraform vs CDK vs click-ops.** Default proposal: Terraform.
5. **Airflow webserver public exposure.** Behind ALB with basic auth (the
   `_AIRFLOW_WWW_USER_*` flow we already have) is the path of least
   resistance. Alternative: keep it private and tunnel via SSM session.
   Default proposal: public + basic auth, IP-allowlisted to author's home
   IP via a security-group rule.
6. **One-shot DB init story.** Run `psql -f contracts/sql/0*.sql` from the
   author's laptop against the RDS endpoint once at provisioning, or wire
   it as an ECS task. Default proposal: laptop-once, document the command.
7. **Frontend host.** Amplify (default) vs keep Vercel (zero-effort).
8. **Image build matrix.** Both `linux/amd64` and `linux/arm64` (Graviton
   tasks/EC2 are cheaper)? Default: arm64-only — all images already build
   under `arm64` locally on the author's M-series mac.
9. **dbt deployment.** Currently runs from inside the Airflow scheduler
   container. That stays the same: the Airflow image bundles the project
   source and `uv run dbt build` works. Confirm no one wants a separate
   dbt-runner task.
10. **Bus-factor / DR.** Single AZ accepted? RDS single-AZ has no failover.
    For a portfolio, yes. Document the limitation.

## 8. Out of scope (deferred to later WPs or rejected outright)

- Multi-AZ anything.
- IaC for Pinecone, Logfire, LangSmith (they remain console-managed).
- Custom CloudWatch dashboards / X-Ray / Glue Schema Registry / Athena
  over the warehouse — Logfire + dbt cover the equivalent ground.
- WAF / Shield / GuardDuty — not justified at portfolio traffic.
- AWS Cost Explorer alerts: nice-to-have, mention in F1 README polish.
- Migrating off Pinecone to OpenSearch Serverless or pgvector. Different
  ADR.
- Replacing Anthropic with Bedrock-hosted Claude. Different ADR; would
  shift the LLM-spend line but doesn't change deployment topology.

## 9. Draft ADR 006 — Deploy backend to AWS (supersedes ADR 003)

> **Not committed yet.** This is the proposed text for Phase 2 to confirm
> and persist as `.claude/adrs/006-aws-deploy.md`, with ADR 003 marked
> `superseded by 006`.

```markdown
# 006 — Deploy backend to AWS instead of Railway

Status: proposed
Date: 2026-04-29
Supersedes: 003

## Context

ADR 003 picked Railway as the production host for Airflow and the API,
based on cost and the desire to ship a real Airflow rather than a managed
shell. Since then, the author has decided to retarget the production
deployment to AWS to strengthen the portfolio narrative around managed
cloud services. The decision affects four tracks: TM-A3 (Postgres host),
TM-A4 (Kafka host), TM-A5 (compute + Airflow), and TM-E4 (frontend host).

## Decision

Deploy the backend on AWS (`eu-west-2`) using:

- **ECS Fargate** for the FastAPI service, the six TfL ingestion daemons,
  the Airflow webserver, and the Airflow scheduler. One service per task,
  desired-count = 1 each, behind an Application Load Balancer for the two
  HTTP-facing tasks (FastAPI + Airflow webserver).
- **RDS PostgreSQL** `db.t4g.micro` single-AZ for the warehouse and the
  Airflow metadata DB (one instance, two logical concerns — same trade-off
  as ADR 003).
- **Self-managed Redpanda** single-node on EC2 `t4g.small` in the same VPC
  as the consumers and producers. Kafka-wire compatibility means no client
  changes; ADR 001 still applies.
- **ECR** for image storage, **Secrets Manager** for the 11 real secrets,
  **SSM Parameter Store** for plain configuration, **CloudWatch Logs** for
  task stdout/stderr, **S3** for Airflow remote logs.
- **Amplify Hosting** for the Next.js frontend, replacing Vercel.
- **Terraform** under `infra/terraform/` as the source of truth for all of
  the above.
- **GitHub Actions** continues to run `make check`; on `main` it pushes
  images to ECR (via OIDC, no long-lived keys) and triggers
  `aws ecs update-service --force-new-deployment`.

Steady-state cost: ~£100-120/mo post free tier; ~£90-105/mo during the
12-month RDS free tier.

## Consequences

- **Pros**: AWS-native portfolio signal; one Postgres still serves both
  warehouse and Airflow; no client refactor (Kafka wire stays);
  Terraform tree under `infra/` is itself a strong artefact; Logfire +
  LangSmith observability story unchanged.
- **Cons**: ~3-4× the monthly cost of the Railway/Supabase plan; one extra
  EC2 to patch (the Redpanda broker); single-AZ posture means an AZ outage
  takes the demo down. All acceptable at portfolio scale.
- **Single AZ accepted.** Documented in the README as a portfolio-scale
  trade-off; multi-AZ would push monthly cost above £200 with no demo
  benefit.
- **MSK rejected.** Serverless control-plane minimum (~£430/mo) and
  provisioned `kafka.t3.small` (~£70/mo) both cost more than the entire
  rest of the platform. Self-managed Redpanda on `t4g.small` keeps the
  budget honest while preserving the Kafka wire promise. If the project
  ever justifies a managed broker, MSK provisioned is the easy migration.
- **MWAA rejected.** Managed Airflow at ~£295/mo defeats the lean-by-
  default principle. LocalExecutor on Fargate retains the same Airflow
  scope as ADR 003.
- **Vercel → Amplify swap.** Phase 2 must verify the Next.js 16 server-
  component path on Amplify. If a blocker surfaces, fall back to keeping
  Vercel (carve-out documented as a known compromise).
- **Cost ceiling alarm.** Phase 2 should add a CloudWatch billing alarm
  via SNS → email at £130/mo to catch surprises early.
```

## 10. Sources I read while writing this

- `CLAUDE.md` — tech stack, observability rule, lean-by-default principle,
  commit-format hard rule.
- `ARCHITECTURE.md` — current "Deployment" table.
- `.claude/adrs/001-redpanda-over-kafka.md`, `003-airflow-on-railway.md`,
  `004-logfire-langsmith-split.md` — existing ADR shapes; ADR 003 is the
  one this WP supersedes.
- `SETUP.md` — accounts table (TfL, Anthropic, OpenAI, Pinecone, LangSmith,
  Logfire, Supabase, Redpanda Cloud, Railway, Vercel, Linear).
- `PROGRESS.md` — current WP status, especially TM-A2 (Airflow DAGs) and
  TM-D5 (agent + new `analytics.chat_messages` table from
  `contracts/sql/004_chat.sql`).
- `docker-compose.yml` — service inventory and environment surface.
- `airflow/Dockerfile`, `airflow/requirements.txt`, `src/ingestion/Dockerfile` —
  prod image story.
- `pyproject.toml` — runtime deps that need to be bundled into prod images.
- `.env.example` — full secret + config surface to map onto Secrets Manager
  and Parameter Store.
- `contracts/sql/00*.sql` — the four init scripts that must run once on the
  RDS instance.
