# Setup step-by-step — tfl-monitor

This document guides you through creating the project from scratch: local init, GitHub, Linear, integration, and executing TM-000. **Order matters** — doing it out of order creates duplicate issues or broken links.

---

## Critical creation order (read this before starting)

```
1. Initialise local project with uv + git
   ↓
2. Create the five starting files (CLAUDE.md, AGENTS.md, SETUP.md, TM-000-spec.md, README stub)
   ↓
3. Create the GitHub repo via gh CLI (creates, links remote, pushes)
   ↓
4. Create Linear workspace + team (one-time)
   ↓
5. Install Linear ↔ GitHub integration (workspace-level)
   ↓
6. Create Linear project and labels
   ↓
7. Create Linear issues (via Linear MCP in Claude Code)
   ↓
8. Execute TM-000 in Claude Code
   ↓
9. After TM-000 is merged: enable branch protection on main
```

**Why this order:**

- The Linear ↔ GitHub integration is **workspace-level**, not project-level. It must be installed before creating the project so issues have auto-link hooks from the moment they're created.
- Branch protection comes **after** TM-000, not before, because the first PR's CI has nothing to check until TM-000 introduces the CI workflow.

---

## Step 1 — Initialise the local project

### 1.1 Create the working directory

```bash
mkdir -p ~/projects/tfl-monitor
cd ~/projects/tfl-monitor
```

### 1.2 Initialise with `uv`

```bash
uv init --bare --python 3.12
```

**Why `--bare`**: by default `uv init` creates a sample `hello.py`, `README.md`, and `.python-version`. `--bare` skips those — we'll write our own README, and a throwaway `hello.py` has no place here.

**Why `--python 3.12`**: pins the Python version immediately so `uv` doesn't pick up whatever is on the system.

After this you'll have:

```
tfl-monitor/
├── pyproject.toml     # minimal — expanded in TM-000
└── .python-version    # pinned to 3.12
```

### 1.3 Initialise git

```bash
git init
git branch -M main
```

---

## Step 2 — Create the five starting files

These are the files that seed the repo before TM-000 runs. **Create them using your editor** (VS Code, vim, etc.) rather than shell heredocs — heredocs can get mangled when pasted into terminals, and we want clean content.

From the artefacts of this conversation, copy these files into the repo root:

1. `CLAUDE.md` — rules for Claude Code
2. `AGENTS.md` — rules for Codex
3. `SETUP.md` — this file
4. `README.md` — **stub version** (see §2.1 below)
5. `.gitignore` — (see §2.2 below)

Also:

6. Create the directory `.claude/specs/` and place `TM-000-spec.md` inside it as `.claude/specs/TM-000-spec.md`:

```bash
mkdir -p .claude/specs
# then move or copy TM-000-spec.md into that folder using your editor or `mv`
```

### 2.1 What is the "stub README"?

A stub README is a placeholder — just enough so the repo isn't empty on day one, knowing you'll replace it with the full version in TM-000 (and polish it again in TM-F1). It's the README-equivalent of a 🚧 sign.

Create `README.md` in your editor with exactly this content:

```markdown
# tfl-monitor

Real-time data platform for Transport for London.

🚧 Under construction. See [CLAUDE.md](./CLAUDE.md) and [.claude/specs/TM-000-spec.md](./.claude/specs/TM-000-spec.md) for scope.

Setup instructions: [SETUP.md](./SETUP.md)
```

That's it. Three sentences, three links. TM-000 replaces this with the full README.

### 2.2 Minimal `.gitignore`

Create `.gitignore` in your editor with exactly this content:

```
.env
.env.local
__pycache__/
*.pyc
.venv/
node_modules/
.DS_Store
.ruff_cache/
.mypy_cache/
.pytest_cache/
dist/
build/
*.egg-info/
```

### 2.3 First commit

```bash
git add .
git commit -m "chore: initial scaffold with agent instructions and TM-000 spec"
```

Your local repo is now ready to be pushed.

---

## Step 3 — Create the GitHub repository

### 3.1 Authenticate `gh` CLI (one-time)

If you haven't done this before:

```bash
gh auth login
```

Choose HTTPS + login via browser. Authorise the required scopes.

### 3.2 Create the remote repo and push in one command

```bash
gh repo create hcslomeu/tfl-monitor --public --description "Real-time data platform for Transport for London: streaming pipeline, dbt warehouse, RAG agent." --source=. --remote=origin --push
```

**What each flag does:**

- `--public` — portfolio project, public
- `--description "..."` — repo description (shown under the repo name on GitHub)
- `--source=.` — use the current directory as the source
- `--remote=origin` — set the new repo as the `origin` remote
- `--push` — push immediately after creating

One command: repo created, linked as `origin`, initial commit pushed.

**Verify:**

```bash
gh repo view --web
```

This opens the repo in your browser. You should see `README.md`, `CLAUDE.md`, `AGENTS.md`, `SETUP.md`, and `.claude/specs/TM-000-spec.md` on the default branch.

### 3.3 Do NOT enable branch protection yet

Branch protection goes on **after** TM-000 is merged, in Step 9. Enabling it now would prevent you from pushing the first PR (because there's no CI workflow to pass yet).

---

## Step 4 — Create the Linear workspace and team

### 4.1 Create the workspace (skip if you already have one)

Go to `https://linear.app` → sign up → create a workspace. One-time setup.

### 4.2 Create the team

Workspaces contain teams. Each team has its own identifier (we want `TM`).

**Workspace settings** (click your workspace name top-left → **Settings**) → **Teams** → **Create team**:

- **Name**: `tfl-monitor` (or `Portfolio` if you plan to reuse the team across future portfolio projects)
- **Identifier**: `TM`
- **Team icon**: optional

After creation, issues in this team will be numbered `TM-1`, `TM-2`, and so on.

---

## Step 5 — Install the Linear ↔ GitHub integration

**This must happen BEFORE creating the project or any issues.** The integration is workspace-level — install it once and it covers every team and project.

### 5.1 Install

Still in workspace settings → **Integrations** → **GitHub** → **Connect**.

- Authorise Linear to access your GitHub account
- **Install Linear on GitHub**: select only `hcslomeu/tfl-monitor` (do not grant access to all your repos)

### 5.2 Configure auto-linking

In the GitHub integration panel within Linear, enable:

- ✅ **Link GitHub pull requests to Linear issues** — PRs mentioning the Linear issue ID in title or description auto-link
- ✅ **Update issue status when PR is merged** — merge → issue moves to Done
- ✅ **Create branch from issue** — optional, useful for standardised branch names
- ✅ **Sync PR reviews as comments**

### 5.3 Why the order matters

If you create the project and issues **before** installing the GitHub integration, the issues won't have the "linked PR" hooks properly wired. Linear usually retrofits this, but not reliably — you can end up with issues that accept manual links but don't auto-transition on merge. Safest: integration first, then project, then issues.

---

## Step 6 — Create the Linear project and labels

### 6.1 Create the project

Sidebar → **Projects** → **+ New project**:

- **Name**: `tfl-monitor`
- **Description**: `Portfolio project: real-time TfL data platform with streaming pipeline, dbt warehouse, and RAG agent. See GitHub repo for full spec.`
- **Lead**: you
- **Target date**: leave blank (avoids artificial pressure)
- **Status**: `In progress`

### 6.2 Create the labels

Sidebar → your team → **Settings** → **Labels** → create:

| Label | Suggested colour |
|---|---|
| `track:A-infra` | grey |
| `track:B-ingestion` | blue |
| `track:C-dbt` | green |
| `track:D-api-agent` | purple |
| `track:E-frontend` | orange |
| `track:F-polish` | yellow |
| `phase:0` through `phase:7` | gradient (light → dark) |
| `type:infra` | dark grey |
| `type:feature` | green |
| `type:contract` | red |

You don't need to create all of these manually — **step 7 will prompt Claude Code to check and report any missing labels**, so you can create them on the fly if easier.

---

## Step 7 — Create the Linear issues via Claude Code

### 7.1 Enable the Linear MCP in Claude Code (one-time)

```bash
claude mcp add linear --url https://mcp.linear.app/sse
```

Or edit `~/.config/claude/mcp.json` (path may vary by OS):

```json
{
  "mcpServers": {
    "linear": {
      "url": "https://mcp.linear.app/sse"
    }
  }
}
```

### 7.2 Open Claude Code in the repo

```bash
cd ~/projects/tfl-monitor
claude
```

On the first call to the Linear MCP, Claude Code will trigger an OAuth flow. Approve it.

### 7.3 Prompt to create all 23 issues

Paste this prompt exactly:

````
I need you to create 23 issues in Linear using the Linear MCP. All issues belong to the "tfl-monitor" project under the "TM" team.

Before creating anything in bulk:
1. Use the Linear MCP to list available labels in my workspace.
2. Tell me which of these labels from my intended list are missing, so I can create them manually:
   track:A-infra, track:B-ingestion, track:C-dbt, track:D-api-agent, track:E-frontend, track:F-polish
   phase:0, phase:1, phase:2, phase:3, phase:4, phase:5, phase:6, phase:7
   type:infra, type:feature, type:contract
3. Wait for my confirmation before creating any issue.

Once I confirm, create all 23 issues with this structure:

**Title format**: "TM-XXX: <title>"

**Description template** (same for every issue):

## Objective
<one-sentence description of what this WP delivers>

## Track
<A-infra / B-ingestion / C-dbt / D-api-agent / E-frontend / F-polish>

## Depends on
<comma-separated list of WP IDs, or "none">

## Detailed spec
Spec will be written at `.claude/specs/TM-XXX-spec.md` before execution.

## Acceptance criteria (summary)
<3-5 bullets — expanded in the detailed spec>

## Reference
See repo README for overview. See `.claude/specs/TM-XXX-spec.md` before executing.

---

Here are the 23 issues with their metadata. Use this exactly:

| WP ID | Title | Track | Depends on | Phase | Objective |
|---|---|---|---|---|---|
| TM-000 | Contracts and scaffold | — | none | 0 | Produce frozen contracts (Pydantic, OpenAPI, SQL, dbt sources) plus minimal scaffolding for every service. |
| TM-A1 | Docker Compose: Postgres + Redpanda + Airflow + MinIO | A-infra | TM-000 | 1 | Bring up all local services via docker compose with healthchecks. |
| TM-B1 | Async TfL client and real fixtures | B-ingestion | TM-000 | 1 | Implement the async TfL API client and generate real response fixtures. |
| TM-C1 | dbt scaffold with sources | C-dbt | TM-000 | 2 | Initialise the dbt project with sources pointing at raw tables. |
| TM-D1 | FastAPI skeleton with 501 stubs plus Logfire wiring | D-api-agent | TM-000 | 2 | Stand up FastAPI with all endpoints returning 501 and Logfire configured. |
| TM-B2 | Producer line-status to Kafka | B-ingestion | TM-A1, TM-B1 | 3 | Poll line-status every 30s and publish validated events to Kafka. |
| TM-B3 | Consumer line-status to Postgres | B-ingestion | TM-B2 | 3 | Consume line-status topic and write to raw.line_status. |
| TM-C2 | dbt staging plus first mart for line_status | C-dbt | TM-C1 | 3 | Build stg_line_status plus mart_tube_reliability_daily with tests. |
| TM-D2 | Wire status/reliability endpoints to Postgres | D-api-agent | TM-C2 | 3 | Replace 501 stubs with real SQL against the mart layer. |
| TM-E1 | Next.js scaffold plus claude.design import plus Network Now | E-frontend | TM-D2 | 3 | Import design from claude.design and wire the Network Now view to the API. |
| TM-B4 | Topics arrivals and disruptions | B-ingestion | TM-B3 | 4 | Add producers and consumers for the two remaining topics. |
| TM-C3 | Remaining marts plus dbt tests plus exposures | C-dbt | TM-C2 | 4 | Build disruption and bus marts with tests and dbt exposures. |
| TM-D3 | Remaining endpoints (disruptions, bus) | D-api-agent | TM-C3 | 4 | Implement the remaining warehouse-backed endpoints. |
| TM-E2 | Disruption Log view | E-frontend | TM-D3 | 4 | Build the Disruption Log view wired to the API. |
| TM-A2 | Airflow DAGs: nightly dbt plus static ingest | A-infra | TM-C3 | 5 | Write and test the two Airflow DAGs locally. |
| TM-D4 | RAG ingestion: Docling to Pinecone | D-api-agent | TM-000 | 5 | Ingest three TfL PDFs through Docling into Pinecone. |
| TM-D5 | LangGraph agent with SQL tool plus RAG tool | D-api-agent | TM-D4, TM-D2 | 6 | Build the routing agent with SQL and RAG tools, using Pydantic AI for tool-level extraction. |
| TM-E3 | Chat view with SSE streaming | E-frontend | TM-D5 | 6 | Build the Ask tfl-monitor chat view with SSE. |
| TM-A3 | Supabase Postgres provisioning | A-infra | end of phase 4 | 7 | Provision Supabase and migrate schema. |
| TM-A4 | Redpanda Cloud Serverless | A-infra | TM-A3 | 7 | Provision Redpanda Cloud and configure TLS/SASL. |
| TM-A5 | Railway deploy: Airflow plus API plus agent plus workers | A-infra | TM-A3, TM-A4 | 7 | Deploy backend services to Railway with env wiring. |
| TM-E4 | Vercel deploy | E-frontend | TM-A5 | 7 | Deploy Next.js to Vercel pointing at the Railway backend. |
| TM-F1 | README polish plus demo video plus live URL | F-polish | TM-E4 | 7 | Finalise the README, shoot demo video, add live URL. |

Apply these labels to each issue:
- one track label (e.g. track:A-infra)
- one phase label (e.g. phase:3)
- one type label (use type:infra for all TM-A* and TM-000, type:contract for anything modifying contracts, type:feature for everything else)

Priority: leave all at Medium.

After creating, give me a summary with:
- Total issues created
- Any issues that failed (with reason)
- The Linear IDs assigned (so I can cross-reference with WP IDs in PR titles)

Respond in Brazilian Portuguese throughout this task.
````

### 7.4 What to expect

Claude Code will first list your labels and tell you which are missing. Create any missing ones manually, then reply `confirm` (or similar) and it will bulk-create the 23 issues.

Budget: ~5 minutes for label verification + confirmation + ~5 minutes for bulk creation.

After this step, verify in Linear that the issues appear under the `tfl-monitor` project with the correct labels.

---

## Step 8 — Execute TM-000

Before starting: make sure all local tools and accounts are ready.

### 8.1 Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| Docker + Compose | Docker 24+, Compose v2 | `https://docs.docker.com/get-docker/` |
| `uv` | 0.5+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `pnpm` | 9+ | `npm install -g pnpm@latest` or `corepack enable pnpm` |
| Node.js | 22 LTS | via `fnm`, `nvm`, or `asdf` |
| `make` | recent | native on macOS/Linux; Windows: WSL2 |
| `git` | 2.40+ | native |
| `gh` CLI | 2.50+ | `brew install gh` or `https://cli.github.com/` |
| Claude Code | latest | `https://claude.com/download` |

Verify all:

```bash
docker --version
uv --version
pnpm --version
node --version
make --version
git --version
gh --version
```

### 8.2 Accounts and keys

Before running TM-000, have these ready (they go in your local `.env`, never in the repo):

| Service | How to get | Cost |
|---|---|---|
| TfL API key | `api-portal.tfl.gov.uk/signup` → subscribe to "500 requests per min" | Free |
| Anthropic API key | `console.anthropic.com` | Pay-as-you-go (pennies) |
| OpenAI API key | `platform.openai.com` | Pay-as-you-go |
| Pinecone | `pinecone.io` → free tier (serverless) | Free |
| LangSmith | `smith.langchain.com` → free tier (5k traces/mo) | Free |
| Logfire | `logfire.pydantic.dev` → free tier (10M spans/mo) | Free |
| Supabase | `supabase.com` → free tier (from TM-A3 onward) | Free |
| Redpanda Cloud | `cloud.redpanda.com` → Serverless free tier (from TM-A4) | Free |
| Railway | `railway.com` → add payment method (from TM-A5) | ~£5/mo for Airflow |
| Vercel | `vercel.com` → free hobby tier | Free |
| Linear | `linear.app` → free tier | Free |

### 8.3 Open a fresh Claude Code session

Start a clean session (run `/clear` if you were using the same session for issue creation):

```bash
cd ~/projects/tfl-monitor
claude
```

### 8.4 Prompt to execute TM-000

Paste this prompt exactly:

```
Read the following files in this order and then wait for my go-ahead before writing any code:

1. CLAUDE.md
2. AGENTS.md
3. .claude/specs/TM-000-spec.md

Once you've read all three, confirm back to me in Portuguese:
- Which language you'll respond in (should be PT-BR)
- Which language code will be in (should be English)
- Whether you understood the three-phase approach
- Any ambiguities or contradictions you spotted between the three files

Then wait. Do not start Phase 1 until I reply with "go".

When I say "go", execute TM-000 strictly following the three-phase approach in CLAUDE.md:

PHASE 1 — Research (read-only):
- Explore the repo state; identify anything that already exists versus what needs to be created
- Write findings to .claude/specs/TM-000-research.md
- Stop and summarise in chat; wait for my confirmation before Phase 2

PHASE 2 — Planning:
- Read the research file
- Produce .claude/specs/TM-000-plan.md with explicit internal sub-phases, file-by-file breakdown, and success criteria (automated + manual) for each sub-phase
- List explicitly what will NOT be built (deferred to later WPs)
- Stop and summarise; wait for my confirmation before Phase 3

PHASE 3 — Implementation:
- Execute the plan sub-phase by sub-phase
- Run `make check` at the end
- When done, prepare the git commands (add, commit, push) as text for me to copy and run — DO NOT run them yourself
- All commit messages must use inline -m "..." format, never heredoc (EOF) format

Remember:
- Respond in Brazilian Portuguese throughout
- Code, docstrings, commit subjects, and error messages in English
- Stop and ask if anything contradicts the spec
- Do not install dependencies beyond what pyproject.toml specifies
```

### 8.5 What to expect

Claude Code will confirm its understanding, wait for your `go`, then walk you through the three phases. Budget: ~4–5 hours for TM-000 complete.

At the end, it provides git commands as text — copy them to your terminal, review the diff, and run them yourself. The PR will be opened via `gh pr create` once you push the branch.

---

## Step 9 — Enable branch protection (after TM-000 is merged)

Now that the CI workflow exists, add light branch protection.

On GitHub: **Settings → Branches → Add branch protection rule**

- **Branch name pattern**: `main`
- ✅ Require a pull request before merging
- ✅ Require status checks to pass before merging → select the `python` and `frontend` jobs from your CI workflow
- ✅ Require conversation resolution before merging
- ✅ Include administrators (the portfolio signal — you can't bypass your own rules)
- ❌ Do NOT require reviews (you're solo — you'd block yourself)
- ❌ Do NOT require signed commits (unnecessary friction)

### Why bother on a solo project?

Not for security (no one is attacking your portfolio). It's for the signal it sends to interviewers: *"Every change goes through a PR with CI, and I don't bypass my own rules."* They see a clean linear history of PR merges, each referencing a WP, each passing CI. That reads as professional discipline.

### When it will annoy you

Small typo fixes now require a branch + PR + CI. Live with it — the signal is worth the friction.

---

## Step 10 — Cadence after TM-000

### 10.1 Two-agent rule

At most **two simultaneous Claude Code sessions** on parallel WPs. Recommended pairings:

- Phase 1: TM-A1 (terminal 1) + TM-B1 (terminal 2)
- Phase 2: TM-C1 (terminal 1) + TM-D1 (terminal 2)
- Phase 4: TM-B4 + TM-C3 (then TM-D3 serial, TM-E2 serial)
- Phase 5: TM-A2 + TM-D4 (pure parallel — different tracks)

Serial (1 agent at a time):

- Phase 3 (vertical slice)
- Phase 6 (agent needs RAG + SQL both ready)
- Phase 7 (deployment — not safely parallelisable)

### 10.2 Ritual per WP

For each WP:

1. Create branch:
   ```bash
   git checkout -b feature/TM-XXX-short-description
   ```
2. Open Claude Code in the repo
3. Prompt:
   ```
   Read CLAUDE.md, AGENTS.md, and .claude/specs/TM-XXX-spec.md. Execute following the three phases. Respond in Brazilian Portuguese.
   ```
4. On completion: `make check` passes, git commands ready as text
5. Open PR:
   ```bash
   gh pr create --title "feat: TM-XXX description" --body "Closes <Linear issue ID>"
   ```
6. **Request Codex review** before merging
7. Merge → Linear auto-moves the issue to Done

### 10.3 Writing future specs

Specs for post-TM-000 WPs don't exist yet. Options:

**Option A (recommended)**: write one spec at a time, on demand, via this chat or a new one. Advantage: each spec is informed by the real state of the repo at that moment.

**Option B**: generate all specs up front in a batch. Advantage: initial speed. Disadvantage: specs drift from reality after the first change.

Suggestion: **Option A**, writing the next pair (TM-A1 + TM-B1) before starting Phase 1.

---

## Final checklist before starting

- [ ] Local repo initialised with `uv init --bare --python 3.12`
- [ ] `CLAUDE.md`, `AGENTS.md`, `SETUP.md`, `README.md` stub, `.gitignore` in place
- [ ] `.claude/specs/TM-000-spec.md` in place
- [ ] First commit done
- [ ] GitHub repo created via `gh repo create` with push
- [ ] Linear workspace, team (`TM` identifier), and GitHub integration installed
- [ ] Linear project `tfl-monitor` and labels created
- [ ] 23 issues created via Claude Code + Linear MCP
- [ ] All local tools installed and verified
- [ ] All API keys and accounts in hand (free tiers are enough)
- [ ] Linear MCP connected in Claude Code locally

If everything's ✅: you're ready to run TM-000.

Branch protection is enabled only in Step 9, **after** TM-000 is merged.

---

## Quick troubleshooting

**"`uv init` says directory is not empty"**
Run it from a fresh directory. `uv init --bare` wants an empty directory (or one containing only `.git`).

**"`gh repo create` asks for SSH vs HTTPS"**
Either works. SSH is nicer long-term (no repeated auth), but HTTPS is simpler if you haven't set up SSH keys on GitHub.

**"Linear isn't auto-linking PRs"**
Check the PR title or body contains the Linear issue ID (`TM-X` as Linear sees it, not the WP ID).

**"Duplicate Linear issue after creating a branch"**
You created the issue via Linear AND the branch via `gh issue develop`. Use only one source.

**"Commit rejected by branch protection"**
Never commit directly to `main`. Always via PR.

**"`make bootstrap` fails with 'uv: command not found'"**
`uv` isn't on your PATH. Reopen the terminal or check `~/.cargo/bin` (or the install path reported by the installer).

**"Claude Code doesn't read CLAUDE.md"**
Restart Claude Code. It reads `CLAUDE.md` at session start.

**"Codex isn't flagging over-engineering"**
Ensure `AGENTS.md` is committed at the repo root. Codex reads `AGENTS.md` automatically.

**"Logfire dashboard is empty despite setting the token"**
The `logfire.configure(send_to_logfire="if-token-present")` only activates when the token is present at process startup. Restart the service after editing `.env`.

**"LangSmith traces not appearing"**
Ensure `LANGSMITH_TRACING=true` is set before the Python process starts. LangGraph reads it at import time.
