# Napkin Runbook

Repo-specific runbook. Read first thing every session and curate. High-signal
recurring guidance only — not a session log.

## Curation Rules

- Re-prioritize on every read.
- Keep recurring, high-value notes only.
- Max 10 items per category.
- Each item includes date + "Do instead".

## Execution & Validation (Highest Priority)

1. **[2026-04-26 / re-confirmed 2026-04-29] `Agent` tool's `isolation: "worktree"` may NOT isolate physical paths**
   Two parallel teammates spawned with `isolation: "worktree"` ended up sharing `/Users/humbertolomeu/tfl-monitor` and committing directly into the parent branch. Second occurrence on TM-D5 (PR #44): `data-layer` and `agent-core` agents serialised through the parent checkout (agent-core's `f107802` landed before data-layer's three commits) — the disjoint file sets saved the day, not the param. `git worktree list` confirms no extra worktree was ever created.
   Do instead: when dispatching ≥2 teammates in parallel, instruct each one in its prompt to run `git worktree add /tmp/<member-name>-worktree HEAD` as step 0 before any edits, OR dispatch them serially. Never trust `isolation: "worktree"` alone for multi-agent concurrency on this machine.

2. **[2026-04-26] CodeRabbit posts new threads after every push (re-review)**
   Round 1 review threads got resolved, push happened, CodeRabbit re-reviewed and opened 3 new threads on the round-2 commit. Ruleset blocks merge until those resolve too.
   Do instead: plan ≥2 review-fix rounds per PR. Brief teammates that "review-fix → push → CodeRabbit re-runs → expect more threads" is the normal flow, not anomaly.

3. **[2026-04-26] Post PR-level decision summary BEFORE resolving threads**
   Before calling `resolveReviewThread`, comment on the PR with `Applied / Rejected with rationale / Already addressed` matrix. Audit trail beats "all green, no explanation" pattern.
   Do instead: template at https://github.com/hcslomeu/tfl-monitor/pull/27#issuecomment-4322119719. Reuse for every review round.

4. **[2026-04-26] `gh pr update-branch` triggers fresh CI + may unresolve nothing — but unblocks BEHIND state**
   PR after merge of base PR shows `mergeStateStatus: BEHIND`. Direct merge fails. `gh pr update-branch <num>` rebases on main; CI re-runs; threads stay resolved (good).
   Do instead: `gh pr update-branch N && gh pr checks N --watch --required && gh pr merge N --squash --delete-branch`.

5. **[2026-04-26] Verification gate before every push: lint + test + bandit + make check**
   Skipping any one is how merge-blocker bugs leak in.
   Do instead: `uv run task lint && uv run task test && uv run bandit -r src --severity-level high && make check` — all four exit 0.

6. **[2026-04-28] Resolve PR threads only where a fix was applied; rejected threads stay open**
   For threads where you push back with a rationale instead of applying the suggestion, do NOT call `resolveReviewThread` — the human reviewer (the author) decides. Resolving a rejected thread reads as "I bypassed the review". The PR-level audit comment + the on-thread rationale reply are sufficient.
   Override only on explicit team-lead green-light, e.g. to unblock a `required_review_thread_resolution: true` policy when the rejected thread is the last blocker. Even then, post the audit reply first, get the green-light, then resolve — never the other way round.
   Do instead: after replying with rationale, leave the resolve to the author. Track unresolved count via `reviewThreads.nodes[] | select(.isResolved == false)` so you know whether the PR is merge-blocked.

## Shell & Command Reliability

1. **[2026-04-26] Branch protection lives in rulesets, not classic API**
   `gh api repos/<owner>/<repo>/branches/main/protection` returns 404 ("Branch not protected") even when protection rules exist.
   Do instead: `gh api repos/<owner>/<repo>/rules/branches/main` returns the active ruleset entries (`required_review_thread_resolution`, `required_status_checks`, etc.).

2. **[2026-04-26] Auto-merge not enabled in this repo**
   `gh pr merge --auto ...` errors with "Auto merge is not allowed for this repository (enablePullRequestAutoMerge)".
   Do instead: `gh pr checks <num> --watch --required` (blocks until required CI passes), then `gh pr merge <num> --squash --delete-branch`.

3. **[2026-04-26] Linear MCP tool schemas don't surface via ToolSearch in this session**
   `claude mcp list` shows `claude.ai Linear: ✓ Connected` but `ToolSearch` queries return zero matching tools, and listing resources shows none for Linear.
   Do instead: use the GitHub issue mirror — Linear↔GitHub integration assigns GitHub issue numbers that match Linear IDs (TM-N). `gh issue list --repo hcslomeu/tfl-monitor --state all --limit 40 --json number,title,state,labels` resolves the WP-to-Linear mapping fast.

4. **[2026-04-26] Inline `-m "..."` commits, NEVER heredoc**
   Author's terminal mangles heredoc commit messages. Multi-paragraph commit bodies use multiple `-m` flags (git concatenates with blank lines).
   Do instead: `git commit -m "subject" -m "body para 1" -m "body para 2"`. Heredoc is OK for `gh pr create --body "$(cat <<'EOF' ... EOF)"` (PR body), NOT for commit messages.

5. **[2026-04-26] Resolve PR review threads via GraphQL only**
   GitHub REST has no "resolve thread" endpoint.
   Do instead:
   ```bash
   gh api graphql -f threadId="$tid" -f query='mutation($threadId: ID!){ resolveReviewThread(input: {threadId: $threadId}){ thread { isResolved } } }'
   ```
   List unresolved with `gh api graphql ... reviewThreads(first:100) { nodes { id isResolved } }`.

6. **[2026-04-26] `gh pr checks --watch` may auto-promote to background**
   Long timeouts trip the harness's background-promotion. Output goes to `/private/tmp/claude-501/.../tasks/<id>.output`; you get a task-completion notification.
   Do instead: pass `run_in_background: true` explicitly so the promotion is intentional, then `Read` the output file when notified.

7. **[2026-04-26] `claude mcp get '<server name with spaces>'` errors out**
   Even with quotes, names like `claude.ai Linear` are rejected ("No MCP server found with name").
   Do instead: skip `claude mcp get` for spaced names; use `claude mcp list` for status and `ListMcpResourcesTool --server '<name>'` for resource enumeration.

8. **[2026-04-29] Bundled rename + delete-remote git ops trip the sandbox**
   `git branch -m old new && git push origin -u new && git push origin --delete old` is denied as a single shell call (the harness flags the destructive delete inside the chain). Even rerunning just the rename+push together still got refused with "Deleting the remote branch ..." even though no delete was in the command.
   Do instead: split into separate `Bash` calls — first `git branch -m`, then `git push origin -u <new>`, leave the orphaned `origin/<old>` ref alone unless the user explicitly asks to delete (then run `git push origin --delete <old>` standalone with explicit user approval).

## Domain Behavior Guardrails

1. **[2026-04-26] `required_review_thread_resolution: true` blocks merge until ALL threads resolved**
   `mergeable: true, mergeable_state: blocked` even when CI is fully green and `required_approving_review_count: 0`. The blocker is unresolved threads.
   Do instead: always re-query unresolved count after fixes (`reviewThreads.nodes[] | select(.isResolved == false)`) and resolve every one before retrying merge.

2. **[2026-04-26] `bandit -r src` ≠ HIGH-only — needs `--severity-level high`**
   Without the flag, all severities are reported, polluting "no findings" assertions.
   Do instead: always invoke `uv run bandit -r src --severity-level high`. CI's `.github/workflows/ci.yml` already does this; specs and gates must match.

3. **[2026-04-26] Test/source imports use `ingestion.foo` (no `src.` prefix)**
   `pyproject.toml` has `pythonpath = ["src"]`. Using `from src.ingestion.foo import X` AND `from ingestion.foo import X` in different files makes mypy strict raise "Source file found twice under different module names".
   Do instead: pick one — `from ingestion.tfl_client.client import TflClient` (matches existing `from api.main import app` pattern). Document this in module docstrings if helpful.

4. **[2026-04-26] `.claude/specs/` is meta, not a code track — bundling across WPs is OK**
   Codex flags cross-track spec files as P1 scope violation, but AGENTS.md §1 lists track directories as `src/`, `dbt/`, `web/`, `tests/`, `airflow/`, `contracts/` — not `.claude/`.
   Do instead: bundle Phase A research+plan files into the first PR of a multi-WP batch so worktrees branched off main inherit them. Defend via PR-level reply with the AGENTS.md track-list excerpt.

5. **[2026-04-26] Linear↔GitHub integration aligns IDs**
   Linear team identifier `TM` produces issues TM-2, TM-3, … and the GitHub mirror assigns matching `gh issue` numbers. `Closes TM-N` in PR body auto-transitions on merge.
   Do instead: cross-reference `gh issue list` once per session to confirm WP↔Linear mapping (TM-000=TM-2, TM-A1=TM-3, TM-B1=TM-4, TM-C1=TM-5, TM-D1=TM-6, etc.).

6. **[2026-04-26] TM-000 over-delivered scope of TM-C1 and parts of TM-D1**
   Always run a research pass against the spec's stated AC before treating a WP as net-new work. The dbt scaffold + FastAPI 501 stubs + Logfire wiring landed in TM-000.
   Do instead: Phase 1 research first; if AC already met, propose "close as already-delivered" with a docs-only PR plus any missing safety nets (e.g. drift tests, parametrised 501 lock, prod CORS origin).

7. **[2026-04-26] Synthetic IDs need full-fidelity input fields**
   `_synthetic_disruption_id` initially hashed only `category + description + affected_routes`; TfL emits multiple records sharing description but differing in `type` / `closureText`. Hash must include all disambiguating fields.
   Do instead: when designing synthetic keys against lossy upstream data, include every field that could legitimately distinguish two records. Add a regression test against a real fixture proving distinct rows produce distinct keys.

8. **[2026-04-26] Python `hash()` is randomised per process — never use for persistent IDs**
   Hash randomisation salts each interpreter run; `hash("x")` differs between invocations.
   Do instead: `hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:N]` for stable digests.

9. **[2026-04-29] `pydantic-ai>=1.75` required when `anthropic>=0.96`**
   `anthropic 0.96` dropped/renamed the `UserLocation` symbol that `pydantic-ai 1.22` imports directly from the Anthropic provider. Lock resolved to two pydantic-ai versions (1.75 + 1.85) and crashed at agent compile time on the older one.
   Do instead: when bumping the Anthropic SDK or adding any LangChain/LangGraph dep that pulls anthropic 0.96, also raise the `pydantic-ai>=` floor to `>=1.75` in `pyproject.toml` and run `uv lock` to confirm a single resolved version.

## User Directives

1. **[2026-04-26] Respond in PT-BR; persist everything in English**
   CLAUDE.md §"Language and communication" is binding. Chat is PT-BR; commits, PR titles+bodies, branch names, issue text, code, docstrings, error messages, tests are English. CAVEMAN mode is on by default — drop articles/filler in PT-BR replies.

2. **[2026-04-26] Provide git commands as text by default**
   CLAUDE.md §"Commit rules": git commands go to chat for the author to copy. Execute only with explicit "go ahead" / "merge" / similar permission.

3. **[2026-04-26] No `Co-Authored-By` lines in commits**
   Do instead: never append the trailer; never use `--no-verify`, `--no-gpg-sign`.

4. **[2026-04-26] Use agent-team (`TeamCreate` + members) for parallel work, not standalone worktree agents**
   User explicitly prefers the team mechanism over independent worktree dispatches.
   Do instead: `TeamCreate` → `TaskCreate` per WP → `Agent` with `team_name` + `name` + `isolation: "worktree"` → assign owners via `TaskUpdate` → wait for SendMessage reports → `TeamDelete` after work merges.

5. **[2026-04-26] Max 2 simultaneous WPs (CLAUDE.md §"WP scope rules")**
   User has overridden to 3 once with explicit confirmation. Default to 2 unless user says otherwise.
