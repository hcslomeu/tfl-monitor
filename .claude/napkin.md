# Napkin Runbook

Repo-specific runbook. Read first thing every session and curate. High-signal
recurring guidance only — not a session log.

## Curation Rules

- Re-prioritize on every read.
- Keep recurring, high-value notes only.
- Soft cap ~10 items per category: when a category exceeds it, prune or merge the lowest-value item on the next read. Favour recording a fresh high-value lesson now over hard-blocking; trim on the next curation pass.
- Each item includes date + "Do instead".

## Execution & Validation (Highest Priority)

1. **[2026-04-26 / re-confirmed 2026-04-29 / re-confirmed 2026-05-19] Parallel sessions clobber the parent checkout — `isolation: "worktree"` is NOT enough; explicit `git worktree` is the only safe mitigation**
   Confirmed three times. Round 1 (TM-D5 PR #44): two `Agent` teammates spawned with `isolation: "worktree"` shared `/Users/humbertolomeu/tfl-monitor` and committed directly into the parent branch; agent-core's `f107802` landed before data-layer's three commits, saved only by disjoint file sets. Round 2 (PRs #87/#88, 2026-05-19): a sibling Claude session on `feature/perf-api-lazy-imports` repointed `feat/deploy-retry-budget`'s local ref, leaked stashes across branches, and reverted unstaged edits to `src/api/*.py` mid-task. Round 3 (PR #89, same day): web-track session saw its working tree mutated by the concurrent API-track session; `EnterWorktree` was disabled by the background-job runtime, so no automatic isolation was available. `git worktree list` always shows a single worktree.
   Do instead: when ≥2 sessions or teammates must run concurrently, each one MUST execute as its first step `git fetch origin && git worktree add --detach "$HOME/.claude/jobs/<jobid>/wt" <remote-sha>`, edit + commit inside that path, `git push origin HEAD:<branch>` (the explicit `origin` is required — `git push HEAD:<branch>` parses `HEAD:<branch>` as a remote name and fails), then `cd "$HOME" && git worktree remove --force "$HOME/.claude/jobs/<jobid>/wt"` (the `cd` is required — `git worktree remove` refuses to delete a worktree that contains the current shell cwd). The detached-HEAD form keeps the worktree immune to branch-ref repointing from peer sessions; pinning to `<remote-sha>` (not the local branch) keeps it immune to ref drift. Do NOT rely on `isolation: "worktree"` and do NOT trust `EnterWorktree` in background-job sessions — pinned to the main checkout by the runtime.

2. **[2026-05-19] Mid-session branch switches in this harness silently revert unstaged edits**
   Hit repeatedly on PRs #88 + #89. A tool-call sequence `Edit → git checkout <other-branch> → git checkout -` does NOT preserve the dirty edits — the working tree returns with the file at the version from the first `checkout`'s target, not pre-checkout state. No error, no warning. Likely interaction between the harness's file-state tracking and git's dirty-checkout semantics. Reproduced multiple times on `src/api/*.py` during PR #88; same failure mode bit `web/components/*` during PR #89.
   Do instead: commit each batch of edits BEFORE any `git checkout` / `git stash pop`. After any branch switch, verify expected state with `grep -c "<marker>" <file>` or `git log -1 --format=%s` before trusting prior tool-output snapshots. If a `checkout` is unavoidable mid-edit, stash explicitly first (`git stash push -u -m "wip" -- <paths>`) and pop after — explicit stash survives where dirty-checkout does not.

3. **[2026-04-26] CodeRabbit posts new threads after every push (re-review)**
   Round 1 review threads got resolved, push happened, CodeRabbit re-reviewed and opened 3 new threads on the round-2 commit. Ruleset blocks merge until those resolve too.
   Do instead: plan ≥2 review-fix rounds per PR. Brief teammates that "review-fix → push → CodeRabbit re-runs → expect more threads" is the normal flow, not anomaly.

4. **[2026-05-12] AI reviewers re-flag stale comments at the latest commit_id — verify file state before re-fixing**
   On PR #56 round 2, Gemini's first-round comments (textarea outline, mobile grid) came back attached to the *new* commit `9cb1b15` with shifted line numbers, even though both were already fixed in that same commit. Without checking the file, `/review-pr` reads them as fresh findings and triggers a wasted second round.
   Do instead: after a push, when fetching inline comments, always `Read` the cited `path:line` and confirm the issue still exists in current code before applying any change. If the fix already landed in a prior commit on the branch, mark the comment "Already Addressed" in the review summary and skip. Distinguishes genuinely new findings (e.g. CodeRabbit's `--accent-display` contrast comment that surfaced only after the first fix landed) from stale references to closed issues.

5. **[2026-04-26] Post PR-level decision summary BEFORE resolving threads**
   Before calling `resolveReviewThread`, comment on the PR with `Applied / Rejected with rationale / Already addressed` matrix. Audit trail beats "all green, no explanation" pattern.
   Do instead: template at https://github.com/hcslomeu/tfl-monitor/pull/27#issuecomment-4322119719. Reuse for every review round.

6. **[2026-04-26] `gh pr update-branch` triggers fresh CI + unblocks BEHIND state**
   PR after merge of base PR shows `mergeStateStatus: BEHIND`. Direct merge fails. `gh pr update-branch <num>` rebases on main; CI re-runs; threads stay resolved (good).
   Do instead: `gh pr update-branch N && gh pr checks N --watch --required && gh pr merge N --squash --delete-branch`.

7. **[2026-04-26] Verification gate before every push: lint + test + bandit + make check**
   Skipping any one is how merge-blocker bugs leak in.
   Do instead: `uv run task lint && uv run task test && uv run bandit -r src --severity-level high && make check` — all four exit 0.

8. **[2026-04-28] Resolve PR threads only where a fix was applied; rejected threads stay open**
   For threads where you push back with a rationale instead of applying the suggestion, do NOT call `resolveReviewThread` — the human reviewer (the author) decides. Resolving a rejected thread reads as "I bypassed the review". The PR-level audit comment + the on-thread rationale reply are sufficient.
   Override only on explicit team-lead green-light, e.g. to unblock a `required_review_thread_resolution: true` policy when the rejected thread is the last blocker. Even then, post the audit reply first, get the green-light, then resolve — never the other way round.
   Do instead: after replying with rationale, leave the resolve to the author. Track unresolved count via `reviewThreads.nodes[] | select(.isResolved == false)` so you know whether the PR is merge-blocked.

9. **[2026-05-16] Dashboard rewrites can orphan wired fetchers without a build failure**
    On TM-F2 research, discovered that TM-E5 (PR #54)'s dashboard-collapse rewrite deleted the wired `ChatView` component but kept `web/lib/api/chat-stream.ts` on `main`. The replacement `web/components/dashboard/chat-panel.tsx` only echoes locally — `send()` calls `setMessages` + an optional `onSend` prop but never `streamChat()`. Build stayed green because the orphaned fetcher's own unit tests pass in isolation, and `app/page.tsx` does not pass an `onSend` handler. The regression surfaced three WPs later when TM-F2 asked "is the chat actually live?".
    Do instead: when a WP deletes or replaces a wired component, before merge run `grep -r "<fetcher-name>" web/components web/app` for every fetcher under `web/lib/api/` (and every tool under `src/api/agent/`, every dbt mart's downstream exposure, etc.). A fetcher with zero call-site imports is a smell — either the rewrite is incomplete or the fetcher is dead code; resolve before merging the rewrite. Build-green ≠ wiring-correct: Biome / `tsc --noEmit` do not fail on an unused export, and the orphan's unit tests stay green because they were authored against the fetcher, not the consumer.

10. **[2026-05-19] `PR merged` ≠ `deployed` — four silent GHA deploy failures hid behind a "✅ shipped" PROGRESS row for five days**
    TM-A5 PR #69 squash-merged 2026-05-14 with `PROGRESS.md` set to `✅ 2026-05-15`, but the first end-to-end successful deploy to the Lightsail box actually landed only on 2026-05-19. Four GHA `Deploy` workflow runs went red between those dates and nobody noticed because none of them blocked anything visible: (a) `scripts/deploy.sh` ran `docker compose up --build | tail` without `set -o pipefail`, so `tail` exit 0 masked `docker compose` exit 1 (no container actually started); (b) the box filled to 100 % disk during image unpack — nvidia-cu13 libs + 3× duplicated ingestion images (~6 GB each) blew through the 50 GB free, root-caused and fixed by PR #80 (CPU-only torch + RAG group split + producers/consumers image-share); (c) the GHA `Build + restart + healthcheck` step's `ssh` lacked `ServerAliveInterval`, so buildkit's >4 min silent unpack dropped the connection with `client_loop: send disconnect: Broken pipe`. The first three failures were observable only by reading the run logs; the workflow exited red but no chat ping fired, and `PROGRESS.md` was never re-checked against the public URL.
    Do instead: [updated 2026-10-12 for ADR 015] every WP that changes how the API is built or deployed (`vercel.json`, `[tool.vercel]`, runtime deps) MUST close with an external smoke against the live URL — `curl -fsS https://tfl-monitor-api.humbertolomeu.com/health` plus one live endpoint — not just "the PR landed green". Check the Vercel deployment state (MCP `list_deployments`/`get_deployment`) before claiming deployed. Treat `PROGRESS.md` rows as aspirational until that smoke runs.

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

6. **[2026-05-18] Vercel preview deployments are SSO-gated — verify which build a URL serves before triaging "missing feature" reports**
   When the user reports "feature is missing on the deployed page", the first reflex is to check which deployment they're hitting. `tfl-monitor.vercel.app` (production) always serves `main`; PR previews live at `*-hcslomeus-projects.vercel.app` URLs and 302 to `vercel.com/login` for any unauthenticated client (Playwright / curl / incognito). On PR #77, the user saw the production URL and concluded the new WIP pill was broken — actually the PR was still unmerged, so prod (main) didn't have it yet. The empty LineGrid + 0/0/0/0 counts were a separate pre-existing backend outage on `tfl-monitor-api.humbertolomeu.com`.
   Do instead: before debugging a missing-feature report, run `gh pr view <N> --json state,mergedAt` and inspect the URL in the report — production URL = `main` snapshot, only the merged state matters there. For pre-merge verification, run `pnpm --dir web dev` locally against the PR checkout or open the preview while logged in to Vercel as the project owner. Don't script automation against `*-projects.vercel.app` URLs — auth always wins.

7. **[2026-05-18] `ExitWorktree` with `action: "remove"` after a squash-merge requires `discard_changes: true`**
   Squash-merge produces a new SHA on `main`, so the worktree's original commits look "unmerged" to ExitWorktree's safety check. On PR #77 cleanup the tool reported "Discarded 2 commits" even though the work was fully on `main` as `7bdcce5`. The discard is a true-no-op in this scenario.
   Do instead: after `gh pr merge <N> --squash`, first confirm `gh pr view <N> --json state,mergeCommit -q '{state, sha: (.mergeCommit.oid // "pending")[:7]}'` reports `state: "MERGED"` with a valid SHA, then call `ExitWorktree(action: "remove", discard_changes: true)`. Don't let the "discarded N commits" message bait a panic restore — those commits exist under the squash SHA on `main`.

8. **[2026-05-11] `gh pr merge --admin` is per-action gated by the hook — pre-confirm with the user**
   Even after the user authorizes "merge all PRs", the harness hook will deny the *first* `gh pr merge --admin` call with reason: "Merging PR #N to default branch via --admin bypasses review and was not explicitly authorized". Generic "go ahead" / "run all the commands" is not enough — the denial requires an explicit, scoped acknowledgement of the `--admin` bypass.
   Same applies to `git push --force-with-lease`: separate authorization, denied with reason "Force-push rewrites remote branch history (Git Destructive); user authorized merging PRs but not force-pushing." Treat `--admin` merge and `--force-with-lease` as two distinct authorizations.
   Do instead: before the first `--admin` merge, ask explicitly e.g. "merge all PRs with `--admin`" and wait for the user to repeat the `--admin` keyword. For stacked-PR force-pushes, ask "authorize force-push" separately. Once authorized in-session, subsequent calls in the same session pass.

9. **[2026-05-15 / re-confirmed 2026-05-18] `gh pr merge --delete-branch` fails when `main` is checked out in another worktree**
   Running `gh pr merge <N> --squash --delete-branch` from either the main checkout OR a sibling worktree aborts with `failed to run git: fatal: 'main' is already used by worktree at '/Users/humbertolomeu/tfl-monitor'`. Hit on PR #68, PR #69, and again on PR #77 — gh's post-merge bookkeeping (`git checkout main && git pull && git branch -D <feature>`) trips on the existing worktree pin. The server-side merge usually still lands; the local cleanup (delete remote branch + delete local branch) is what fails, leaving the PR merged but the branch orphaned both locally and remotely.
   Do instead: invoke from a non-git cwd with `--repo` explicit — `cd /tmp && gh pr merge <N> --squash --delete-branch --repo hcslomeu/tfl-monitor`. If the failure already happened, finish cleanup manually in this order: (1) `git push origin --delete <branch>` for the remote; (2) `ExitWorktree(action: "remove", discard_changes: true)` if inside the worktree — this deletes the worktree directory AND the local branch and restores the session to the parent checkout; (3) from the parent checkout, `git pull --ff-only` to sync `main`. If you removed the worktree via bare `git worktree remove <path>` instead of `ExitWorktree`, also run `git branch -D <branch>` because bare-git does not delete the branch ref. Always confirm with `gh pr view <N> --json state,mergeCommit -q '{state, sha: (.mergeCommit.oid // "pending")[:7]}'` before assuming the merge landed.

10. **[2026-05-14] `vercel env add <name> preview --value <v> --yes` rejects its own suggested non-interactive form**
    On TM-E4 Phase 6 deploy, the CLI emitted `{status: "action_required", reason: "git_branch_required"}` JSON and exited non-zero when called with exactly the form its error-message hint suggests. Neither a TTY shim (`script -q /dev/null`) nor piping `printf "\n"` over stdin resolves this; the CLI still fails to accept the "all preview branches" path. The production-only form `vercel env add <name> production --value <v> --yes` works.
    Do instead: skip the CLI for preview-scoped env vars; POST to the REST API directly — `curl -X POST "https://api.vercel.com/v10/projects/<projectId>/env?teamId=<teamId>" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"key":"<KEY>","value":"<VAL>","type":"plain","target":["preview"]}'`. **For secret values**, swap `-d '<inline>'` for `--data-binary @body.json` (or `< body.json`) so the value stays out of shell history and process listings. Token path is OS-dependent: macOS `~/Library/Application\ Support/com.vercel.cli/auth.json`, Linux `~/.local/share/com.vercel.cli/auth.json` (XDG default), key `.token` in both. Confirm via `GET /v9/projects/<projectId>/env?teamId=<teamId>`.

11. **[2026-05-27] Auto-mode classifier blocks ANY direct push to protected `main` — even a 2-line docs commit — unless explicitly authorized per-action**
    On TM-30 wrap-up, `git push origin main` of the docs commit (PROGRESS.md + current-wp.md marking the WP done) was denied: "Direct git push of a docs commit to the protected default branch (main) bypasses PR review; user authorized merging PR #122, not a direct push to main." This is DISTINCT from the general "run git directly" allowance (memory `feedback_run_git_commands_directly`) and from the `gh pr merge --admin` gating (item #8): authorizing a PR merge does NOT authorize a subsequent direct-to-main push, and each is classified separately. The local `git commit` (no push) is always allowed — only the push to the protected ref trips the classifier. Historically docs commits DO land on main directly (e.g. `e7a67f6`), so the block is a per-session auth gap, not a repo policy against it; the owner is a ruleset bypass-actor so the server accepts the push once the classifier lets it through.
    Do instead: at WP completion, expect the PROGRESS.md/current-wp.md docs push to need a fresh explicit authorization even right after an authorized PR merge. Pre-ask once: "authorize direct push to main for the docs commit" (or batch it: "merge #N and push the docs commit to main directly"). Commit locally first (always allowed) so the work is never lost, then push once authorized. Don't burn a denied call assuming the merge authorization carried over.

12. **[2026-10-12] Vercel Python `[tool.vercel] entrypoint` is a FILE path in module notation, not an import path — `src.api.main:app`, not `api.main:app`**
    With the src layout, `entrypoint = "api.main:app"` fails `vercel build` with `PYTHON_ENTRYPOINT_NOT_FOUND` (no `api/main.py` at the repo root). `src.api.main:app` works: Vercel loads `src/api/main.py` as module `src.api.main`, while its `from api...` imports resolve to the project wheel it installs from `uv.lock` (hatch `packages`). `vercel build` runs fully offline with a stub `.vercel/project.json` (`{"projectId":"prj_local","orgId":"team_local","settings":{"framework":"fastapi"}}`), which is the cheap way to validate entrypoint, bundle contents, and size before touching a real project.
    Do instead: validate any change to `pyproject.toml` `[tool.vercel]`, `vercel.json`, or runtime deps with a local `vercel build --yes` in a scratch copy of the repo, then inspect `.vercel/output/functions/*.func/.vc-config.json` (`filePathMap` must not include `tests/`, `docs/`, `.claude/`, `web/`) and the venv size under `.vercel/python/.venv`.

## Domain Behavior Guardrails

1. **[2026-05-20] TfL free `/Line/Mode/{modes}/Disruption` returns empty `affectedRoutes`/`affectedStops` — the route/stop fan-out lives only on `/Status?detail=true`**
   `/api/v1/disruptions/recent` was serving `affected_routes: []` and `affected_stops: []` on every row. The pipeline was forwarding the upstream payload faithfully: verified live (2026-05-20) that the free-tier `/Line/Mode/{modes}/Disruption` endpoint returns `affectedRoutes: []` and `affectedStops: []` on every record across every mode (`tube`, `elizabeth-line`, `overground`, `dlr`, `bus`). The committed fixture `tests/fixtures/tfl/disruptions_tube.json` mirrored the upstream and the unit tests passed on a broken contract; the bug only surfaced once the API was wired to real Supabase data. The richer fan-out exists on `/Line/Mode/{modes}/Status?detail=true`, where each `Line.lineStatuses[*].disruption` carries populated `affectedRoutes` (route sections of the parent line) and `affectedStops` (entries with `naptanId`). One TfL-observed quirk: the same line can carry multiple `lineStatuses` whose nested disruptions share `category` / `closureText` / `description` but differ in `affectedStops` (District-line dual-incident on 2026-05-20: same `severeDelays` text, 5-stop vs 4-stop incidents).
   Do instead: never source ingestion off `/Line/Mode/{modes}/Disruption` — switch to `/Status?detail=true` and walk `Line → lineStatuses[] → disruption`. Set `affected_routes = [parent Line.id]` and `affected_stops = deduped naptanIds from disruption.affectedStops` (deduplicated in first-seen order — `_extract_ids` does not sort the payload field; sorting happens only inside the synthetic-id hash input below). Include sorted `affected_stops` in any synthetic `disruption_id` hash on top of `category + closure_text + description + affected_routes` — otherwise same-line dual incidents collide on one id and the second event becomes invisible to id-keyed downstream consumers. The pattern shipped in PR #96 (`fix(api): populate affected_routes in /disruptions/recent (TM-26)`): commit `7c6aec8`, `src/ingestion/tfl_client/client.py::fetch_line_disruptions` + `src/ingestion/tfl_client/normalise.py::disruption_payloads`.

2. **[2026-05-14] CSS subgrid with N children > declared tracks silently overlaps cells (Chromium)**
   When `grid-template-rows: subgrid` allocates M tracks and the container has N>M auto-placed children, Chromium does NOT auto-create implicit tracks; the extras stack into the last row, hiding earlier siblings — no warning, no console error, lint and tests stay green. PR #62 surfaced this when `tfl_monitor.css` (verbatim claude.design export) declared `.tfl-left-col, .tfl-right-col { grid-template-rows: subgrid; grid-row: 2 / span 2 }` (2 tracks) with 3 children → `NewsReports` rendered on top of `BusBanner` invisibly. Same effect on right col with `.tfl-right-col .tfl-chat-stack { grid-row: 1 / span 2 }` hiding `LineDetail` behind the chat-card body. Diagnosis required `getBoundingClientRect` via Playwright `browser_evaluate` to see two siblings reporting the same `y`+`h`.
   Do instead: when porting a design-system CSS that uses subgrid, audit child count vs declared row-span before shipping (`document.querySelector('.tfl-left-col').children.length` vs `getComputedStyle(...).gridTemplateRows`). If mismatched, switch the column to plain `display: flex; flex-direction: column` (PR #62's fix). Don't trust visual parity in Storybook/canvas alone — the canvas may have been authored at a different child count and never re-rendered against the final one.

3. **[2026-04-26] `required_review_thread_resolution: true` blocks merge until ALL threads resolved**
   `mergeable: true, mergeable_state: blocked` even when CI is fully green and `required_approving_review_count: 0`. The blocker is unresolved threads.
   Do instead: always re-query unresolved count after fixes (`reviewThreads.nodes[] | select(.isResolved == false)`) and resolve every one before retrying merge.

4. **[2026-04-26] Synthetic IDs need full-fidelity input fields**
   `_synthetic_disruption_id` initially hashed only `category + description + affected_routes`; TfL emits multiple records sharing description but differing in `type` / `closureText`. Hash must include all disambiguating fields.
   Do instead: when designing synthetic keys against lossy upstream data, include every field that could legitimately distinguish two records. Add a regression test against a real fixture proving distinct rows produce distinct keys. See item 2 for the 2026-05-20 follow-up adding `affected_stops` to the hash after the `/Status?detail=true` switch.

5. **[2026-04-26] Python `hash()` is randomised per process — never use for persistent IDs**
   Hash randomisation salts each interpreter run; `hash("x")` differs between invocations.
   Do instead: `hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:N]` for stable digests.

6. **[2026-04-26] `bandit -r src` ≠ HIGH-only — needs `--severity-level high`**
   Without the flag, all severities are reported, polluting "no findings" assertions.
   Do instead: always invoke `uv run bandit -r src --severity-level high`. CI's `.github/workflows/ci.yml` already does this; specs and gates must match.

7. **[2026-04-26] Linear↔GitHub integration aligns IDs**
   Linear team identifier `TM` produces issues TM-2, TM-3, … and the GitHub mirror assigns matching `gh issue` numbers. `Closes TM-N` in PR body auto-transitions on merge.
   Do instead: cross-reference `gh issue list` once per session to confirm WP↔Linear mapping (TM-000=TM-2, TM-A1=TM-3, TM-B1=TM-4, TM-C1=TM-5, TM-D1=TM-6, etc.).

8. **[2026-05-14] Vercel deploy lifecycle quirks: first deploy targets prod, CLI `link` ≠ Git integration, monorepo subdir needs `rootDirectory` PATCH**
    Three related Vercel gotchas surfaced on TM-E4 Phase 6 deploy:
    1. **First `vercel deploy` on a fresh project = production**, even without `--prod`. The response showed `"target": "production"` and the `tfl-monitor.vercel.app` apex alias was attached immediately. Use `--target=preview` if you actually want a preview deployment.
    2. **`vercel link` only writes `.vercel/project.json` — it does NOT connect the GitHub webhook.** The CLI deploy works from the linked dir, but auto-deploy on push is OFF until the author clicks "Connect Git Repository" in the project's Settings → Git page and authorizes the Vercel GitHub app on the specific repo. The CLI cannot do this.
    3. **After Git integration is connected, monorepo subdir projects break with `Error: No Next.js version detected`** because the project's `rootDirectory` defaults to `null` (repo root) when created via CLI from inside the subdir. The CLI build worked because `pwd` was the subdir; Git-triggered builds clone the repo at the root. Fix: `curl -X PATCH "https://api.vercel.com/v9/projects/<projectId>?teamId=<teamId>" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"rootDirectory":"<subdir>"}'`, then `vercel redeploy <last-good-url>` (or push a new commit) to exercise the integration. Hook denies this PATCH without explicit user authorization — pre-ask before running.
    Do instead: when setting up Vercel for a monorepo, run `vercel link` from the subdir, then immediately PATCH `rootDirectory`, then ask the author to connect Git in the dashboard. Verify with `vercel ls <project>` after first auto-trigger — a Ready 30s build vs. Error 3s build is the signal.

9. **[2026-05-27] TfL `/StopPoint/Search` ranks a HUB id (`HUB*`) top for major interchanges — unusable on JourneyResults (HTTP 300) and Arrivals (0 predictions); deref to a concrete rail child**
    High priority (prod crash). The TM-30 forward resolver (`stations.resolve_name`) mapped a name → top `/StopPoint/Search` match id. For interchanges (Bank, King's Cross, Paddington, Victoria, Liverpool Street, …) the top match is a **hub** id like `HUBBAN`, NOT a station NaPTAN. A hub id is not a usable endpoint: `/Journey/JourneyResults/.../to/HUBBAN` returns **HTTP 300** (TfL falls back to fuzzy text matching — `HUBBAN` matched "HUBBARD DRIVE" in Kingston, useless disambiguation options), and `/StopPoint/HUBBAN/Arrivals` returns **0 predictions**. The uncaught `TflClientError` from the 300 propagated through LangGraph's `ToolNode` — whose `_default_handle_tool_errors` **re-raises** non-`ToolException` errors — leaving an AIMessage tool_call with no ToolMessage, so the NEXT model step hit `_validate_chat_history` and the whole `chat/stream` died with `end:error`. Hand-built fixtures + the hardcoded-NaPTAN unit test (`940GZZLUBNK`) all passed; only a live agent smoke surfaced it. NOT a Pydantic-AI/name-extraction problem — the LLM extracted `origin`/`destination` correctly; the failure is purely name→id resolution. Concrete NaPTANs (`940GZZLUBNK` Bank tube, 44 arrivals / 3 journeys) work fine.
    Do instead: when resolving a free-text station name for journey/arrival endpoints, detect a hub top-match by id prefix (`HUB`), fetch `/StopPoint/{hubId}`, and pick the highest-priority **rail child** by mode (`tube > elizabeth-line > dlr > overground > national-rail`) from its `children[]` (each child carries `naptanId` + `modes`). On a transient deref failure DON'T cache (return the hub id for that call but leave `_NAME_CACHE` untouched so the next request retries — same no-poison policy as the reverse `_NAPTAN_CACHE`); a fetch that succeeds with no rail child IS a definitive result, safe to cache. ALWAYS wrap `TflClient` calls inside LangGraph `@tool` bodies in `try/except` returning a friendly string — LangGraph re-raises non-`ToolException` and crashes the stream otherwise (this corrected a wrong PR #122 review-rejection). Shipped in PR #123 (`de7e0ed`, ADR 010): `TflStopPoint.children`, `stations._deref_hub` + `_pick_rail_child`, try/except in `plan_journey_tool`/`get_arrivals_tool`. Verify any TfL-tool change with a LIVE agent smoke (`POST /api/v1/chat/stream`), not just fixtures — hand-built fixtures hid this for the entire WP.

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
