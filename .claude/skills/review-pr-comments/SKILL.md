---
name: review-pr
description: Fetch and summarize AI-generated PR review comments (CodeRabbit, Gemini Code Assist, Codex, Claude, Copilot) and suggest actionable fixes
user-invocable: true
---

# Skill: Review PR Comments

Fetch review comments from AI code review agents on a GitHub PR, categorize them by severity, and suggest fixes.

## When to Use

- After CI passes and AI reviewers have posted comments on a PR.
- When you want a consolidated summary of all review feedback before addressing it.

**Always check ALL of these reviewers** (any combination may be active on a given repo):
- CodeRabbit (`coderabbitai[bot]`)
- Gemini Code Assist (`gemini-code-assist[bot]`)
- Codex (`chatgpt-codex-connector[bot]`)
- Claude (`claude[bot]`)
- Copilot (`copilot-pull-request-reviewer[bot]`, `github-actions[bot]` running Copilot review actions)

A reviewer being silent or rate-limited is a valid finding — note it as "no comments" or "rate-limited", do not assume absence means nothing to address.

## Inputs

The PR number is passed as an argument: `/review-pr 53`

If no argument is provided, detect the current branch and find the open PR for it.

## Workflow

1. **Fetch PR comments** using `gh` CLI. Three surfaces — query all three, they hold different content:
   - Inline review comments: `gh api repos/{owner}/{repo}/pulls/{number}/comments`
   - Review bodies (summary verdicts): `gh api repos/{owner}/{repo}/pulls/{number}/reviews`
   - Issue-thread comments (Claude posts here, as do CodeRabbit summaries + rate-limit notices): `gh api repos/{owner}/{repo}/issues/{number}/comments`
   - Detect the repo owner/name from the current git remote.

2. **Filter** to AI reviewers. Use this jq pattern across all three surfaces:
   ```bash
   --jq '.[] | select(.user.login | test("(?i)coderabbit|gemini-code-assist|codex|^claude\\[bot\\]$|copilot"))'
   ```
   Always enumerate all five reviewers explicitly in the output (`coderabbitai[bot]`, `gemini-code-assist[bot]`, `chatgpt-codex-connector[bot]`, `claude[bot]`, `copilot-pull-request-reviewer[bot]`) — if one posted nothing, list it as "no comments" or "rate-limited" so the user can see at a glance which reviewers were active. Do not silently drop a reviewer just because it had no findings.

3. **Categorize** each comment:
   - **Critical** (must fix): Security issues, bugs, crashes, type errors.
   - **Warning** (should fix): Missing error handling, edge cases, best practices.
   - **Suggestion** (consider): Style, naming, refactoring ideas, future improvements.
   - **Already addressed**: Comments marked with "Addressed in commit" or similar, or whose target code no longer exists at the referenced line.

4. **For each actionable comment**, provide:
   - File and line reference.
   - What the reviewer flagged.
   - The suggested fix (code diff if provided by the reviewer).
   - Your assessment: agree, disagree with reason, or "style preference — skip".

5. **Output format**:

```
## PR #N Review Summary

### Reviewer status
| Reviewer | Findings |
|---|---|
| CodeRabbit | <count or "rate-limited" or "no comments"> |
| Gemini | <count or "no comments"> |
| Codex | <count or "no comments"> |
| Claude | <count, plus Approve/Comment/Request-changes verdict if posted> |
| Copilot | <count or "no comments"> |

### Critical (must fix)
1. **[file:line]** — [description] _(reviewer consensus: A + B)_
   Fix: [what to change]

### Warning (should fix)
1. **[file:line]** — [description] _(reviewer: X)_
   Fix: [what to change]

### Suggestion (consider)
1. **[file:line]** — [description] _(reviewer: X)_
   Assessment: [agree/skip with reason]

### Already Addressed
- [description] — resolved in commit [hash]

### Skipped (style preferences)
- [description] — [why skipping]
```

## Important Notes

- Do NOT apply fixes automatically — present the summary for the user to decide. (If the user explicitly says "address them" / "fix them" / "apply suggestions", then apply.)
- Cross-reference suggestions with the project's `CLAUDE.md` coding standards.
- If two or more reviewers flag the same issue, surface the consensus in the line item (`_(reviewer consensus: Claude + Codex + Gemini)_`).
- Flag any suggestions that contradict the project's established patterns.
- Claude reviews live on the **issue-thread** endpoint, not the pull-request reviews endpoint. Skipping the issue-thread query will silently miss every Claude review.
- CodeRabbit posts its summary on the issue thread but its inline findings on the pulls/comments endpoint. Both must be checked.
- Some reviewers (Copilot, Gemini) post under multiple bot identities depending on action vs app configuration. If `gh` shows an unfamiliar `*[bot]` author with a substantive review body, treat it as a real reviewer until proven otherwise.

### Handling Multi-Round Reviews

When a PR has been reviewed multiple times (e.g., after pushing fixes):
- Comments from earlier rounds may reference **code that no longer exists** (stale comments).
- Check if a comment's file path and line still match the current code.
- Mark stale comments as "Already addressed" rather than re-flagging them.
- Focus the summary on **genuinely new** comments from the latest review round.
- Each new push usually triggers a fresh review pass from Claude and Codex; CodeRabbit may rate-limit between rounds — note when this happens.
