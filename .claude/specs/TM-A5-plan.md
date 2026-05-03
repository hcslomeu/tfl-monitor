# TM-A5 — Plan (Phase 2)

Implementation plan for **TM-A5: lean AWS deploy + Bedrock LLM swap**.
Built from `.claude/specs/TM-A5-research.md` (re-scoped after the
2026-04-29 budget reset). Supersedes the original "all-AWS Fargate
pivot" reading of the research file.

## 1. Charter (locked)

Deploy the production stack on **one EC2 spot instance** running the
existing docker-compose layout, swap the Anthropic-direct LLM client
for **AWS Bedrock**, and keep every other tier on its existing free
plan. Goal: $0-5/month after free tiers, $100 AWS credit lasts
~12 months across two portfolio projects.

| Layer | Host | Cost |
|---|---|---|
| Backend compute (FastAPI + collapsed ingestion + Airflow) | **AWS EC2 t4g.small spot** (`us-east-1`), single instance, 24/7 via ASG min=max=1 | ~$4/mo |
| LLM (Sonnet + Haiku) | **AWS Bedrock** (`us-east-1`, `anthropic.claude-3-5-sonnet-20241022-v2:0` + `anthropic.claude-3-5-haiku-20241022-v1:0`) | ~$2-3/mo at portfolio traffic |
| Postgres warehouse + Airflow metadata | Supabase free | $0 |
| Kafka broker | Redpanda Cloud Serverless free | $0 |
| Frontend | Vercel free hobby (`tfl-monitor.vercel.app`) | $0 |
| Vector DB | Pinecone serverless free | $0 |
| Backend HTTPS | DuckDNS subdomain (`tflmonitor.duckdns.org`) + Caddy auto-Let's Encrypt | $0 |
| Image registry | GHCR (GitHub free) | $0 |
| Observability | Logfire + LangSmith free tiers | $0 |

**Steady-state target: ~$6/mo** ($4 EC2 spot + $2 Bedrock).

ADR 003 (Airflow on Railway) becomes superseded by ADR 006 (Bedrock +
single-EC2 deploy), committed in the final PR.

### Files added

```
infra/terraform/
├── README.md
├── main.tf                  # ~150 LoC flat: VPC ref, SG, IAM, ASG, EIP
├── variables.tf
├── outputs.tf
├── versions.tf
├── userdata.sh              # cloud-init: docker, compose, repo clone

infra/
├── docker-compose.prod.yml  # 5 services + Caddy
├── Caddyfile                # reverse proxy with auto-LE
└── .env.example             # production env-var template

scripts/
├── bootstrap-instance.sh    # one-shot: docker login GHCR, compose pull, up
├── deploy.sh                # idempotent redeploy: pull + up
└── duckdns-update.sh        # cron: keep duckdns subdomain → EIP

src/api/Dockerfile           # API-only image (split from ingestion)
src/ingestion/run_producers.py   # collapses 3 producers in one process
src/ingestion/run_consumers.py   # collapses 3 consumers in one process

.github/workflows/deploy.yml # on main push: build + push GHCR + ssm redeploy

.claude/adrs/006-aws-deploy.md  # ADR text in PR-3
```

### Files modified

```
src/api/agent/graph.py            # ChatAnthropic → ChatBedrockConverse
src/api/agent/extraction.py       # pydantic-ai "anthropic:..." → "bedrock:..."
pyproject.toml                    # +langchain-aws, +boto3; -? (anthropic stays as transitive)
uv.lock                           # regenerated
.env.example                      # remove ANTHROPIC_API_KEY, add AWS_REGION + BEDROCK_*_MODEL_ID
docker-compose.yml                # local dev keeps anthropic? — see §2 #5
src/ingestion/Dockerfile          # arm64 base, slim
airflow/Dockerfile                # multi-stage with project source baked
ARCHITECTURE.md                   # deployment table → AWS EC2 + Bedrock + Supabase + Redpanda Cloud + Vercel
README.md                         # deploy section + cost table + provisioning runbook link
PROGRESS.md                       # TM-A3, TM-A4, TM-A5, TM-E4 → ✅
.claude/adrs/003-airflow-on-railway.md  # status: superseded by 006
.gitignore                        # terraform.tfstate*, .terraform/, .env
```

### Untouched

`contracts/openapi.yaml`, `contracts/schemas/*`, `contracts/sql/*`,
`dbt/`, `web/lib`, `web/components`, `web/app`, `src/api/db.py`,
`src/api/schemas.py`, `src/api/main.py` (no CORS or lifespan
changes — Vercel URL already in allowlist), `src/rag/`,
`tests/` (unit tests don't change; integration tests pick up Bedrock
via env-var swap).

### PR sequence (3 PRs under the TM-A5 banner)

| # | Branch | Tracks touched | Approx LoC |
|---|---|---|---|
| **PR-1** | `feature/TM-A5-bedrock-swap` | D-api-agent (`src/api/agent/`) + B-ingestion (`src/ingestion/run_*.py`) — declared cross-track | ~200 source + 80 test |
| **PR-2** | `feature/TM-A5-aws-deploy` | A-infra (`infra/`, `scripts/`, `src/api/Dockerfile`, `airflow/Dockerfile`, `.github/workflows/`) | ~450 |
| **PR-3** | `feature/TM-A5-adr-progress` | meta (`.claude/adrs/`, `ARCHITECTURE.md`, `README.md`, `PROGRESS.md`) | ~250 markdown |

PR-1 declares the cross-track touch in its body (D + B) under ADR 002
§"Consequences" wording: the Bedrock swap is API-owned and the
collapse is mechanical — no contract change. Sibling WPs TM-A3 / TM-A4
/ TM-E4 are absorbed: TM-A3 is "create Supabase project + paste URL",
TM-A4 is "create Redpanda cluster + paste creds", TM-E4 is "vercel
deploy". None warrant a full PR; their work is provisioning steps
inside §3 below.

## 2. Decisions (Phase 2 lock)

| # | Question | Decision |
|---|---|---|
| 1 | Compute platform | **1× EC2 t4g.small spot via ASG min=max=1, `us-east-1`**, single public-subnet default-VPC. ASG re-spawns on spot interruption (~5min downtime/event, ~1-2x/week). |
| 2 | OS / runtime | **Amazon Linux 2023 ARM64 + Docker + Docker Compose v2**. cloud-init in `userdata.sh` installs both, clones the repo, runs `bootstrap-instance.sh`. |
| 3 | Service topology on the box | **5 long-running services** (down from 9): `api`, `producers`, `consumers`, `airflow-webserver`, `airflow-scheduler`, plus `caddy` reverse proxy. Defined in `infra/docker-compose.prod.yml`. |
| 4 | Service collapse | **6 ingestion daemons → 2 processes**: `run_producers.py` runs `LineStatusProducer().run_forever()` + `ArrivalsProducer().run_forever()` + `DisruptionsProducer().run_forever()` under one `asyncio.gather`; `run_consumers.py` mirrors for the three consumers. Existing classes unchanged; entry-point is new. |
| 5 | LLM provider | **Bedrock for prod, Anthropic-direct stays as opt-in for local dev** (`docker-compose.yml` keeps `ANTHROPIC_API_KEY` for the dev developer who has it). Selection by env: when `BEDROCK_REGION` is set, use Bedrock; else fall back to Anthropic-direct. Default `.env.example` flips to Bedrock. |
| 6 | LangChain Bedrock client | **`langchain-aws.ChatBedrockConverse`** (newer Bedrock Converse API, native tool-calling). `ChatAnthropic` import stays as a fallback path gated by env. |
| 7 | Pydantic AI Bedrock | **`pydantic-ai >=1.85` model string `"bedrock:anthropic.claude-3-5-haiku-20241022-v1:0"`**. Already fits the `pydantic-ai>=1.75` line in `pyproject.toml` from TM-D5. |
| 8 | AWS auth on EC2 | **Instance profile** with `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` scoped to the two model ARNs. `boto3` reads creds via IMDSv2; no `AWS_ACCESS_KEY_ID` in `.env`. |
| 9 | AWS auth in CI | **GHA OIDC role** with `ssm:SendCommand` to push redeploys. No long-lived AWS keys in GitHub Secrets — only `AWS_GHA_ROLE_ARN`. |
| 10 | Image registry | **GHCR** (`ghcr.io/<owner>/tfl-monitor-<api\|ingestion\|airflow>`). Free for public repos; GHA workflow uses the built-in `GITHUB_TOKEN`. |
| 11 | Reverse proxy / TLS | **Caddy** in the compose stack, auto-Let's Encrypt via HTTP-01 challenge. Domain: **DuckDNS** (`tflmonitor.duckdns.org` — free). Re-pointable to a custom `.dev` domain by editing one line in the `Caddyfile`. |
| 12 | DuckDNS update | **`scripts/duckdns-update.sh` cron @ 5min** on the box keeps the DuckDNS A record pointing at the current EIP. EIP is stable but the script is cheap insurance against accidental detach. |
| 13 | Image arch | **arm64-only.** All images already build under `arm64` on the author's M-series laptop; t4g instances are arm64. |
| 14 | API + ingestion image split | **Yes** — new `src/api/Dockerfile` produces `tfl-monitor-api`. Faster API rebuilds, ~250 MB image. |
| 15 | Airflow image | **Multi-stage** baking project source + `uv` into `/opt/tfl-monitor`. dbt builds run from inside the scheduler container. No remote logging in v1 — logs land in a docker volume on the host (cheap, sufficient for portfolio). |
| 16 | Secrets management | **Plain `.env` file on the box**, populated by the author once via SSM Session Manager paste. No Secrets Manager / Parameter Store ceremony in v1. Bedrock + S3 access flows through the instance role (no creds in `.env`). |
| 17 | IaC | **Flat Terraform** in `infra/terraform/main.tf` (~150 LoC). No modules, no envs, no remote state. `terraform apply` from the laptop. |
| 18 | Region | **`us-east-1`**. Bedrock Sonnet 3.5 + Haiku 3.5 colocated; cheapest EC2 + EBS prices; TfL API cross-Atlantic adds ~80ms which is fine for 30s polling. |
| 19 | Bus-factor / DR | **Single AZ, single instance accepted.** ASG re-launches on spot kill; ingestion gap during the ~5min restart is fine for portfolio. EBS volume preserved across spot relaunches via the ASG launch-template `BlockDeviceMappings`. |
| 20 | RDS / RDS Proxy | **None.** Supabase remains the warehouse + Airflow metadata DB (one URL, two logical concerns — same trade-off as ADR 003). |
| 21 | Custom domain | **No purchase in TM-A5.** DuckDNS for v1. Author can flip to `api.tflmonitor.<personal-domain>.dev` in TM-F1 by editing `Caddyfile` + `duckdns-update.sh`. |
| 22 | CloudWatch billing alarm | **Enabled at $20/mo** via SNS → email. Cheap insurance — at portfolio scale our actual run-rate is ~$6/mo. |
| 23 | CloudWatch logs | **Skipped.** Container stdout stays in docker on the box; `docker compose logs -f api` is the operator surface. Long-term observability is Logfire (CLAUDE.md hard rule). |
| 24 | Auto-scaling | **None** beyond ASG min=max=1. Single instance per workload. |
| 25 | Bedrock model access | **One-time approval in the Bedrock Console** before deploy. §3 step 1 walks the author through it. |

### Cost lock (steady-state)

| Line | $/mo |
|---|---|
| EC2 t4g.small spot (~70% off on-demand) | ~3-4 |
| EBS gp3 20 GB (free tier covers 30 GB year 1) | 0 year 1 / 1.6 year 2+ |
| Bandwidth (1 GB egress/mo at portfolio traffic) | ~0.10 |
| Bedrock (50 chat sessions × 5 turns × ~1500 tokens) | ~2-3 |
| EIP (free while attached) | 0 |
| Supabase free | 0 |
| Redpanda Cloud Serverless free | 0 |
| Vercel hobby free | 0 |
| Pinecone serverless free | 0 |
| Logfire + LangSmith free | 0 |
| **Total** | **~$5-8/mo** |

$100 credit / 2 projects × 12 months = $4-5/mo budget per project →
fits with margin. CloudWatch billing alarm fires at $20/mo (decision
#22) as the safety net.

## 3. Provisioning runbook (Phase 3)

Everything below runs in this order. Each step has an exit check.
**If reality diverges from this plan in any step, stop and report:**
*"Expected: X. Found: Y. How should I proceed?"*

### Step 0 — Prerequisites on the author's laptop

- AWS CLI v2 configured: `aws configure` with the personal account
  profile, default region `us-east-1`. Verify: `aws sts get-caller-identity`.
- Terraform `>= 1.7` installed: `terraform version`.
- Docker Desktop running locally for image build smoke checks.
- An SSH key for emergency access: `ssh-keygen -t ed25519 -f ~/.ssh/tfl-monitor`.
- The local `.env` already populated for dev (per `.env.example`).

### Step 1 — Bedrock model access (Console)

1. Open `https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess`.
2. Click **Manage model access** → request access to:
   - `Anthropic / Claude 3.5 Sonnet v2`
   - `Anthropic / Claude 3.5 Haiku`
3. Approval is automatic for personal accounts but can take ~30 min.
4. Verify via CLI:
   ```bash
   aws bedrock list-foundation-models --region us-east-1 \
     --query 'modelSummaries[?contains(modelId, `claude-3-5`)].modelId'
   ```
   Both `anthropic.claude-3-5-sonnet-20241022-v2:0` and
   `anthropic.claude-3-5-haiku-20241022-v1:0` must appear.

### Step 2 — Provider sign-ups (free tiers)

For each, the author creates an account if not already, captures the
credentials into a temporary scratchpad, and pastes them into the EC2
`.env` in step 7. **Credentials reference table is in §4 below.**

| Provider | URL | What to capture |
|---|---|---|
| Supabase | https://supabase.com/dashboard | Project ref + DB password → `DATABASE_URL` |
| Redpanda Cloud | https://cloud.redpanda.com | Serverless cluster bootstrap servers + SASL user/pass |
| Pinecone | https://app.pinecone.io | API key (index already provisioned in TM-D4) |
| OpenAI | https://platform.openai.com/api-keys | API key |
| Logfire | https://logfire.pydantic.dev | Token |
| LangSmith | https://smith.langchain.com | API key |
| TfL | https://api-portal.tfl.gov.uk | App key (already obtained) |
| DuckDNS | https://www.duckdns.org | Subdomain (e.g. `tflmonitor`) + token |
| Vercel | https://vercel.com | Project linked to GitHub repo (already done in TM-E1a) |

Initialise the Supabase DB: from the author's laptop, with the `.env`
holding `DATABASE_URL`:

```bash
psql "$DATABASE_URL" \
  -f contracts/sql/001_raw.sql \
  -f contracts/sql/002_ref.sql \
  -f contracts/sql/003_analytics.sql \
  -f contracts/sql/004_chat.sql
```

Initialise Redpanda topics: from the author's laptop with `rpk`
configured against the cluster:

```bash
for t in line-status arrivals disruptions; do
  rpk topic create "$t" --partitions 1 --replicas 1
done
```

### Step 3 — PR-1: Bedrock swap + service collapse

Branch `feature/TM-A5-bedrock-swap`. Single PR.

#### 3.1 Bedrock LLM swap (`src/api/agent/`)

`pyproject.toml` adds:
```toml
"langchain-aws>=0.2",
"boto3>=1.35",
```
`uv lock` regenerates `uv.lock`.

`src/api/agent/graph.py` swap:
```python
import os
from langchain_aws import ChatBedrockConverse
from langchain_anthropic import ChatAnthropic  # kept as opt-in fallback

def _build_chat_model() -> Any:
    bedrock_region = os.environ.get("BEDROCK_REGION")
    if bedrock_region:
        return ChatBedrockConverse(
            model_id=os.environ.get(
                "BEDROCK_SONNET_MODEL_ID",
                "anthropic.claude-3-5-sonnet-20241022-v2:0",
            ),
            region_name=bedrock_region,
            temperature=0.0,
        )
    # Local-dev fallback for developers with an Anthropic key.
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return None
    return ChatAnthropic(
        model_name="claude-3-5-sonnet-latest",
        temperature=0.0,
        anthropic_api_key=anthropic_key,
    )
```

`compile_agent` checks `model is None` and returns `None` if no LLM
backend is reachable. The acceptance criterion in TM-D5 (503 when any
of three keys is missing) becomes "503 when neither Bedrock nor
Anthropic is reachable".

`src/api/agent/extraction.py` swap:
```python
@lru_cache(maxsize=1)
def _normaliser() -> Agent[None, LineId]:
    bedrock_region = os.environ.get("BEDROCK_REGION")
    if bedrock_region:
        model = f"bedrock:{os.environ.get('BEDROCK_HAIKU_MODEL_ID', 'anthropic.claude-3-5-haiku-20241022-v1:0')}"
    else:
        model = "anthropic:claude-3-5-haiku-latest"
    return Agent(model=model, output_type=LineId, instructions="...")
```

#### 3.2 Service collapse (`src/ingestion/`)

`src/ingestion/run_producers.py`:
```python
"""Run all three TfL producers in one asyncio process."""
import asyncio
from ingestion.line_status_producer import LineStatusProducer
from ingestion.arrivals_producer import ArrivalsProducer
from ingestion.disruptions_producer import DisruptionsProducer

async def main() -> None:
    await asyncio.gather(
        LineStatusProducer().run_forever(),
        ArrivalsProducer().run_forever(),
        DisruptionsProducer().run_forever(),
    )

if __name__ == "__main__":
    asyncio.run(main())
```

`src/ingestion/run_consumers.py`: mirror for the three consumers.

Tests: existing producer / consumer unit tests are unchanged. Add one
new test per file (`tests/ingestion/test_run_producers.py`,
`tests/ingestion/test_run_consumers.py`) that monkeypatches each
class's `run_forever` to a no-op and asserts `main()` returns cleanly.

#### 3.3 Acceptance — PR-1

- [ ] `uv run task lint` (ruff + mypy strict) green.
- [ ] `uv run task test` (default suite) green — agent tests pass with both Bedrock and Anthropic env paths via parametrisation; ingestion tests pass with the collapsed entrypoints.
- [ ] `make check` end-to-end clean.
- [ ] PR title `feat(api): TM-A5 Bedrock swap + ingestion entrypoint collapse`. Body declares the cross-track touch (D + B) under ADR 002 §Consequences.

### Step 4 — PR-2: AWS provisioning + deploy

Branch `feature/TM-A5-aws-deploy`. One PR but multiple internal phases.

#### 4.1 Production compose stack (`infra/docker-compose.prod.yml`)

```yaml
# Production compose for the EC2 box. Pulls from GHCR.
# Bedrock auth flows through the EC2 instance profile — no AWS keys here.

services:
  api:
    image: ghcr.io/${GITHUB_OWNER}/tfl-monitor-api:latest
    restart: unless-stopped
    env_file: [.env]
    depends_on: [airflow-scheduler]  # ordering only; not health-gated

  producers:
    image: ghcr.io/${GITHUB_OWNER}/tfl-monitor-ingestion:latest
    command: ["uv", "run", "python", "-m", "ingestion.run_producers"]
    restart: unless-stopped
    env_file: [.env]

  consumers:
    image: ghcr.io/${GITHUB_OWNER}/tfl-monitor-ingestion:latest
    command: ["uv", "run", "python", "-m", "ingestion.run_consumers"]
    restart: unless-stopped
    env_file: [.env]

  airflow-scheduler:
    image: ghcr.io/${GITHUB_OWNER}/tfl-monitor-airflow:latest
    command: ["airflow", "scheduler"]
    restart: unless-stopped
    env_file: [.env]
    volumes: ["airflow-logs:/opt/airflow/logs"]

  airflow-webserver:
    image: ghcr.io/${GITHUB_OWNER}/tfl-monitor-airflow:latest
    command: ["airflow", "webserver"]
    restart: unless-stopped
    env_file: [.env]
    volumes: ["airflow-logs:/opt/airflow/logs"]

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config

volumes: { airflow-logs: {}, caddy-data: {}, caddy-config: {} }
```

#### 4.2 `infra/Caddyfile`

```caddy
{
    email tflmonitor@example.com
}

tflmonitor.duckdns.org {
    handle_path /airflow* {
        reverse_proxy airflow-webserver:8080
    }
    reverse_proxy api:8000 {
        flush_interval -1   # disable buffering for SSE
    }
}
```

#### 4.3 Terraform `infra/terraform/main.tf` (flat ~150 LoC)

```hcl
terraform { required_version = ">= 1.7" }

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "tfl-monitor", ManagedBy = "terraform" } }
}

# --- Default VPC + first public subnet ---
data "aws_vpc" "default" { default = true }
data "aws_subnets" "public" {
  filter { name = "vpc-id"; values = [data.aws_vpc.default.id] }
}
data "aws_ami" "al2023_arm64" {
  most_recent = true
  owners      = ["amazon"]
  filter { name = "name"; values = ["al2023-ami-*-arm64"] }
}

# --- IAM instance profile with Bedrock + SSM ---
resource "aws_iam_role" "ec2" {
  name = "tfl-monitor-ec2"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "bedrock" {
  role = aws_iam_role.ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0",
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "tfl-monitor-ec2"
  role = aws_iam_role.ec2.name
}

# --- Security group ---
resource "aws_security_group" "ec2" {
  name   = "tfl-monitor-ec2"
  vpc_id = data.aws_vpc.default.id
  ingress { from_port = 80;  to_port = 80;  protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }
  ingress { from_port = 443; to_port = 443; protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }
  egress  { from_port = 0;   to_port = 0;   protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }
}

# --- Launch template + ASG (spot, single instance) ---
resource "aws_launch_template" "ec2" {
  name_prefix   = "tfl-monitor-"
  image_id      = data.aws_ami.al2023_arm64.id
  instance_type = "t4g.small"
  iam_instance_profile { name = aws_iam_instance_profile.ec2.name }
  vpc_security_group_ids = [aws_security_group.ec2.id]
  user_data = base64encode(file("${path.module}/userdata.sh"))
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs { volume_size = 20; volume_type = "gp3"; delete_on_termination = false }
  }
  instance_market_options {
    market_type = "spot"
    spot_options { spot_instance_type = "persistent"; instance_interruption_behavior = "stop" }
  }
}

resource "aws_autoscaling_group" "ec2" {
  name                = "tfl-monitor"
  min_size            = 1
  max_size            = 1
  desired_capacity    = 1
  vpc_zone_identifier = [data.aws_subnets.public.ids[0]]
  launch_template { id = aws_launch_template.ec2.id; version = "$Latest" }
  tag { key = "Name"; value = "tfl-monitor"; propagate_at_launch = true }
}

# --- EIP + association via lifecycle hook (script in userdata) ---
resource "aws_eip" "ec2" { domain = "vpc" }

# --- GHA OIDC ---
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_role" "gha" {
  name = "tfl-monitor-gha"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_owner}/${var.github_repo}:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "gha_ssm" {
  role = aws_iam_role.gha.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["ssm:SendCommand", "ssm:GetCommandInvocation"]
      Resource = "*"
    }]
  })
}

# --- Billing alarm ---
resource "aws_sns_topic" "billing" { name = "tfl-monitor-billing" }
resource "aws_cloudwatch_metric_alarm" "billing" {
  alarm_name          = "tfl-monitor-billing-20usd"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600
  statistic           = "Maximum"
  threshold           = 20
  alarm_actions       = [aws_sns_topic.billing.arn]
  dimensions          = { Currency = "USD" }
}

# --- Outputs ---
output "instance_eip"       { value = aws_eip.ec2.public_ip }
output "gha_role_arn"       { value = aws_iam_role.gha.arn }
output "billing_topic_arn"  { value = aws_sns_topic.billing.arn }
```

`variables.tf`: `region` (default `us-east-1`), `github_owner`,
`github_repo` (default `tfl-monitor`).

#### 4.4 `infra/terraform/userdata.sh`

```bash
#!/bin/bash
set -euo pipefail
dnf update -y
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user

# Install docker compose v2 plugin
mkdir -p /usr/libexec/docker/cli-plugins
curl -sSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64" \
  -o /usr/libexec/docker/cli-plugins/docker-compose
chmod +x /usr/libexec/docker/cli-plugins/docker-compose

# Associate the EIP (the EIP is created by Terraform; allocation id passed via tag lookup)
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/instance-id)
ALLOC_ID=$(aws ec2 describe-addresses --region us-east-1 \
  --filters "Name=tag:Project,Values=tfl-monitor" \
  --query 'Addresses[0].AllocationId' --output text)
aws ec2 associate-address --region us-east-1 \
  --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID"

# Clone repo + bootstrap
sudo -u ec2-user git clone https://github.com/${github_owner}/tfl-monitor.git /home/ec2-user/tfl-monitor
echo "Awaiting manual .env paste via SSM Session Manager."
```

#### 4.5 GitHub Actions workflow `.github/workflows/deploy.yml`

```yaml
name: deploy
on:
  push:
    branches: [main]
permissions: { id-token: write, contents: read, packages: write }
jobs:
  build-and-push:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        image:
          - { name: api,        dockerfile: src/api/Dockerfile }
          - { name: ingestion,  dockerfile: src/ingestion/Dockerfile }
          - { name: airflow,    dockerfile: airflow/Dockerfile }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
      - run: |
          docker buildx build \
            --platform linux/arm64 \
            --file ${{ matrix.image.dockerfile }} \
            --tag ghcr.io/${{ github.repository_owner }}/tfl-monitor-${{ matrix.image.name }}:${{ github.sha }} \
            --tag ghcr.io/${{ github.repository_owner }}/tfl-monitor-${{ matrix.image.name }}:latest \
            --push .
  redeploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with: { role-to-assume: ${{ secrets.AWS_GHA_ROLE_ARN }}, aws-region: us-east-1 }
      - run: |
          aws ssm send-command \
            --document-name "AWS-RunShellScript" \
            --targets "Key=tag:Name,Values=tfl-monitor" \
            --parameters 'commands=["cd /home/ec2-user/tfl-monitor && git pull && docker compose -f infra/docker-compose.prod.yml pull && docker compose -f infra/docker-compose.prod.yml up -d"]'
```

#### 4.6 First-deploy sequence

After `terraform apply` finishes:

1. SSH or SSM Session Manager into the box:
   `aws ssm start-session --target <instance-id> --region us-east-1`
2. Paste the `.env` contents (template in `infra/.env.example` filled
   from §4 below) into `/home/ec2-user/tfl-monitor/infra/.env`.
3. Run:
   ```bash
   cd /home/ec2-user/tfl-monitor
   bash scripts/bootstrap-instance.sh
   ```
   The script does: GHCR docker login (using a GitHub PAT with
   `read:packages` pasted into the `.env` once), `docker compose pull`,
   `docker compose up -d`.
4. Update DuckDNS: from any laptop with `curl`,
   ```bash
   curl "https://www.duckdns.org/update?domains=tflmonitor&token=$DUCKDNS_TOKEN&ip=$(terraform -chdir=infra/terraform output -raw instance_eip)"
   ```
   Caddy issues an LE cert on first request to `tflmonitor.duckdns.org`.
5. Smoke:
   ```bash
   curl -fsS https://tflmonitor.duckdns.org/health
   curl -fsS https://tflmonitor.duckdns.org/api/v1/status/live
   curl -fsSN -X POST https://tflmonitor.duckdns.org/api/v1/chat/stream \
     -H 'content-type: application/json' \
     -d '{"thread_id":"smoke","message":"What lines are running?"}'
   ```
6. Update Vercel project env:
   `NEXT_PUBLIC_API_URL=https://tflmonitor.duckdns.org`. Redeploy
   frontend (Vercel auto on next push).
7. Add the Vercel preview URL pattern + Amplify-equivalent URL to the
   FastAPI CORS allowlist if not already covered (TM-D1 already lists
   `https://tfl-monitor.vercel.app`).

#### 4.7 Acceptance — PR-2

- [ ] `terraform validate` + `terraform fmt -check` clean.
- [ ] `terraform apply` succeeds against the personal AWS account.
- [ ] EC2 instance reachable via SSM Session Manager.
- [ ] All 5 docker compose services up: `docker compose ps` shows `running`.
- [ ] `curl https://tflmonitor.duckdns.org/health` → `200 {"status":"ok",...}`.
- [ ] `curl https://tflmonitor.duckdns.org/api/v1/status/live` → `200 [...]`.
- [ ] `curl -N` against `/api/v1/chat/stream` yields ≥ 1 token frame and an `end` frame within 60 s, against Bedrock.
- [ ] Vercel frontend loads, calls land at the EC2.
- [ ] CloudWatch billing alarm visible at $20/mo, SNS subscription confirmed by author email.
- [ ] GHA `deploy.yml` runs green on `main` push (manually trigger first time via empty commit).
- [ ] PR title `infra(aws): TM-A5 EC2 + Bedrock production deploy`.

### Step 5 — PR-3: ADR 006 + docs

Branch `feature/TM-A5-adr-progress`.

- Add `.claude/adrs/006-aws-deploy.md` (~80 LoC) with the agreed text:
  "Single EC2 spot instance + Bedrock + free-tier saas".
- Update `.claude/adrs/003-airflow-on-railway.md` header:
  `Status: superseded by 006`.
- Update `ARCHITECTURE.md` "Deployment" table.
- Update `README.md` with a "Deploy" section that links to this plan
  and shows the cost table from §1.
- Flip `PROGRESS.md` rows: TM-A3 (Supabase = "free tier provisioned"),
  TM-A4 (Redpanda Cloud = "free tier provisioned"), TM-A5 (this WP),
  TM-E4 (Vercel = "live").

#### Acceptance — PR-3

- [ ] All five doc files updated.
- [ ] PR title `docs(arch): TM-A5 ADR 006 + AWS deploy progress`.

## 4. Credentials reference table

Author needs to gather these before Step 4.6. **Bold = secret, do not
commit. Plain = config, OK in `.env.example`.** Order matches
`infra/.env.example`.

| Var | Type | Where it comes from | Notes |
|---|---|---|---|
| `TFL_APP_KEY` | **secret** | TfL Unified API portal (already obtained) | Used by ingestion producers |
| `DATABASE_URL` | **secret** | Supabase project → Settings → Database → Connection string (URI mode) | Includes user, password, host, port, db |
| `KAFKA_BOOTSTRAP_SERVERS` | config | Redpanda Cloud cluster overview | `<cluster>.<region>.redpanda.com:9092` |
| `KAFKA_SECURITY_PROTOCOL` | config | static | `SASL_SSL` |
| `KAFKA_SASL_MECHANISM` | config | static | `SCRAM-SHA-256` |
| `KAFKA_SASL_USERNAME` | **secret** | Redpanda Cloud → Service accounts | |
| `KAFKA_SASL_PASSWORD` | **secret** | Redpanda Cloud → Service accounts | |
| `OPENAI_API_KEY` | **secret** | OpenAI dashboard → API keys | Used by RAG embedder + LlamaIndex query embedder |
| `EMBEDDING_MODEL` | config | static | `text-embedding-3-small` |
| `PINECONE_API_KEY` | **secret** | Pinecone console → API keys | |
| `PINECONE_INDEX` | config | static | `tfl-strategy-docs` |
| `BEDROCK_REGION` | config | static | `us-east-1` (presence enables Bedrock path in graph + extraction) |
| `BEDROCK_SONNET_MODEL_ID` | config | static | `anthropic.claude-3-5-sonnet-20241022-v2:0` |
| `BEDROCK_HAIKU_MODEL_ID` | config | static | `anthropic.claude-3-5-haiku-20241022-v1:0` |
| `LOGFIRE_TOKEN` | **secret** | Logfire dashboard → Tokens | |
| `LANGSMITH_TRACING` | config | static | `true` |
| `LANGSMITH_API_KEY` | **secret** | LangSmith → Settings → API keys | |
| `LANGSMITH_PROJECT` | config | static | `tfl-monitor` |
| `AIRFLOW_ADMIN_USERNAME` | config | author choice | e.g. `admin` |
| `AIRFLOW_ADMIN_PASSWORD` | **secret** | author choice (strong) | Set on first scheduler boot via `airflow users create` in entrypoint |
| `AIRFLOW__CORE__FERNET_KEY` | **secret** | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | Required by Airflow >=2 for connection encryption |
| `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` | **secret** | derived from `DATABASE_URL` | `postgresql+psycopg2://user:pass@host:port/db` (same DB, separate schema `airflow`) |
| `ENVIRONMENT` | config | static | `production` |
| `APP_VERSION` | config | static | `v1.0.0` (bump per release) |
| `GHCR_PAT` | **secret** | GitHub → Settings → Developer settings → Personal access tokens (classic, scope `read:packages` only) | Pasted on the box for the bootstrap `docker login ghcr.io` |
| `DUCKDNS_TOKEN` | **secret** | DuckDNS dashboard | Used by `scripts/duckdns-update.sh` |
| `DUCKDNS_SUBDOMAIN` | config | author choice | e.g. `tflmonitor` (host = `<subdomain>.duckdns.org`) |

**Removed from `.env.example` in PR-1:** `ANTHROPIC_API_KEY` (Bedrock
replaces it; kept commented as opt-in for local dev).

**Not in `.env`** — provided by AWS infrastructure, not the author:
- `AWS_REGION` (overridden by Bedrock auto-detect from instance metadata; we still set `BEDROCK_REGION` explicitly so the code path is environment-driven, not metadata-driven)
- AWS access keys (instance role provides them implicitly via IMDSv2)

**GitHub repo secrets** (Settings → Secrets and variables → Actions):
- `AWS_GHA_ROLE_ARN` (output of `terraform output gha_role_arn`)

That's all. Everything else flows through GitHub's built-in
`GITHUB_TOKEN` for GHCR push.

## 5. What we are NOT doing

- ECS Fargate, EKS, App Runner — over-engineered for one box.
- ALB / Route 53 — Caddy + DuckDNS handles HTTPS for $0.
- Multi-AZ — single AZ accepted; spot interruption ~5min downtime is the documented trade-off.
- RDS — Supabase free covers warehouse + Airflow metadata.
- MSK / self-managed Redpanda on a separate EC2 — Redpanda Cloud Serverless free covers Kafka.
- Secrets Manager / SSM Parameter Store — plain `.env` on the box for v1; flip to Parameter Store in TM-F1 if author wants the AWS-native signal.
- CloudWatch dashboards / X-Ray / Container Insights — Logfire and LangSmith handle observability per CLAUDE.md hard rule.
- Custom domain purchase — DuckDNS for v1, custom in TM-F1.
- Auto-scaling beyond ASG min=max=1 — single instance is the design.
- S3 remote logging for Airflow — host volume is fine for portfolio demo.
- Service mesh, network policies, WAF, Shield, GuardDuty.
- Multi-architecture image builds — arm64 only.
- Remote Terraform state in S3 + DynamoDB lock — local state for v1.
- Bedrock provisioned throughput — on-demand pricing fits portfolio traffic.
- Bedrock guardrails / agents — `langchain-aws.ChatBedrockConverse` direct invocation only.
- Anthropic-direct removal — kept as local-dev opt-in (decision #5).
- Migration off Pinecone / OpenAI / Logfire / LangSmith.
- Linear MCP issue updates — PR bodies close the relevant Linear issues; Linear handles the transition.
- Custom prompt-injection filter — same scope as TM-D5.

## 6. Risks revisited

| Risk | Mitigation |
|---|---|
| Spot interruption mid-demo | ASG `persistent` spot type re-launches; ~5min downtime. Author can switch to on-demand by editing one `instance_market_options` block if a demo is scheduled. |
| Bedrock model access denied | Step 1 verifies access before deploy. If denied, fall back to Anthropic-direct via `.env` (`unset BEDROCK_REGION`, set `ANTHROPIC_API_KEY`). |
| Bedrock Sonnet API surface differs from Anthropic SDK | `ChatBedrockConverse` normalises tool-calling to LangChain's interface; existing tests pass with both backends through the parametrised env path. |
| `pydantic-ai` Bedrock model latency | Haiku-only normaliser, ≤5 invocations per chat turn. ~200ms each. Acceptable. |
| RAM saturation on t4g.small | Tested footprint ~1.4 GB idle, ~1.8 GB during dbt build. Headroom 200-600 MB. If saturation appears, drop Airflow webserver (CLI-only operations) — saves 250 MB. |
| EBS root volume loss on spot reclaim | `delete_on_termination = false` preserves the volume; ASG re-attaches on relaunch. Worst case re-clone repo (idempotent). |
| GHA OIDC token leak | Trust policy gates by `repo:<owner>/tfl-monitor:ref:refs/heads/main`. Even if the role ARN leaks, only that repo+branch can assume. |
| `.env` exposure on the box | `.env` permissions `chmod 600`, owned by `ec2-user`. Accepted for v1. |
| DuckDNS outage | DuckDNS has 99.9%+ uptime; if it dips, demo is down briefly. Free tier risk acknowledged. |
| `make check` cost | No new Python/TS deps require install in CI; the two new ones (`langchain-aws`, `boto3`) install in seconds. |
| Bedrock cost overrun | CloudWatch billing alarm at $20/mo (~10× steady-state) catches anything pathological. |
| Free-tier expiry on Supabase / Redpanda Cloud / Pinecone | All three free tiers are indefinite at portfolio scale. README documents the limits. |
| `airflow db migrate` first-boot ordering | Scheduler entrypoint runs `airflow db migrate` on every start (idempotent). |

### Rollback

Three granularities:

1. **Per-image rollback.** `docker compose pull` against a previous tag, e.g. `:sha-<previous>`. GHCR retains all SHA tags.
2. **Per-PR rollback.** `git revert -m 1 <merge-sha>` then `terraform apply` reverses infra. Bedrock swap revert restores Anthropic-direct path.
3. **Whole-pivot rollback.** ADR 003 (Railway) is preserved in git history. Reverting the three TM-A5 PRs and shipping ADR 003's Railway plan is the documented escape hatch.

## 7. Files expected to change (final)

Counts include both tests and source.

| Category | Added | Modified |
|---|---|---|
| Source | 4 (`run_producers.py`, `run_consumers.py`, `src/api/Dockerfile`, plus the 3 docker compose files in `infra/`) | 3 (`graph.py`, `extraction.py`, `pyproject.toml` + `uv.lock`) |
| IaC | 5 (`main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`, `userdata.sh`) | 0 |
| Caddy / Compose / scripts | 4 (`Caddyfile`, `docker-compose.prod.yml`, `bootstrap-instance.sh`, `deploy.sh`, `duckdns-update.sh`) | 1 (`airflow/Dockerfile` multi-stage; `src/ingestion/Dockerfile` arm64 base) |
| CI/CD | 1 (`.github/workflows/deploy.yml`) | 0 |
| Tests | 2 (`tests/ingestion/test_run_*.py`) | 0 — existing agent tests pick up Bedrock via env parametrisation |
| Docs / ADR | 1 (`.claude/adrs/006-aws-deploy.md`) | 4 (`ARCHITECTURE.md`, `README.md`, `PROGRESS.md`, `.claude/adrs/003-airflow-on-railway.md`) |
| Configs | 1 (`infra/.env.example`) | 2 (`.env.example`, `.gitignore`) |

Total ~23 new files, ~10 modified, ~900-1000 LoC across all three PRs.

## 8. Confirmation gate

Before starting Phase 3, author confirms:

1. **Spot vs on-demand.** Default: t4g.small spot via ASG (~$4/mo). Override = on-demand for $12/mo.
2. **Region.** Default: `us-east-1`. Override = `us-east-2` (slightly cheaper, same Bedrock support) or `eu-west-2` (Bedrock cross-region call adds ~80ms).
3. **DuckDNS subdomain.** Default: `tflmonitor.duckdns.org`. Override = a different subdomain or skip in favour of a personal domain purchased before TM-A5.
4. **GHA OIDC.** Default: yes, enabled. Confirms the GitHub repo full name (`<owner>/tfl-monitor`) for the trust policy.
5. **CloudWatch billing alarm threshold.** Default: $20/mo. Override with another value.
6. **`.env` on the box.** Default: plain file, chmod 600. Override = SSM Parameter Store from day one (adds ~30 LoC of bootstrap).
7. **Cross-track touch declaration.** PR-1 touches `src/api/agent/` (D-track) + `src/ingestion/` (B-track) inside an A-track WP. Confirms acceptance.
8. **Anthropic-direct fallback in code.** Decision #5 keeps the code path for local dev. Confirms the value (vs hard-removing it for cleanliness).
9. **Bedrock model access.** Confirms the author has run Step 1 (or will, before PR-2 deploy time).
10. **Sequencing.** PR-1 (Bedrock + collapse) → PR-2 (deploy) → PR-3 (ADR + docs). Override = different order.

Once confirmed, Phase 3 starts at §3 Step 0.
