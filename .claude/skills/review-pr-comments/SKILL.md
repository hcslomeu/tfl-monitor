---
name: review-pr
description: Fetch and summarize AI-generated PR review comments (CodeRabbit, Gemini Code Assist) and suggest actionable fixes
user-invocable: true
---

# Skill: Review PR Comments

Fetch review comments from AI code review agents on a GitHub PR, categorize them by severity, and suggest fixes.

## When to Use

- After CI passes and AI reviewers (CodeRabbit, Gemini Code Assist) have posted comments on a PR
- When you want a consolidated summary of all review feedback before addressing it

## Inputs

The PR number is passed as an argument: `/review-pr 53`

If no argument is provided, detect the current branch and find the open PR for it.

## Workflow

1. **Fetch PR comments** using `gh` CLI:
   - Inline review comments: `gh api repos/{owner}/{repo}/pulls/{number}/comments`
   - Review bodies: `gh api repos/{owner}/{repo}/pulls/{number}/reviews`
   - Detect the repo owner/name from the current git remote

2. **Filter** to only AI agent comments (look for bot usernames like `coderabbitai[bot]`, `gemini-code-assist[bot]`)

3. **Categorize** each comment:
   - **Critical** (must fix): Security issues, bugs, crashes, type errors
   - **Warning** (should fix): Missing error handling, edge cases, best practices
   - **Suggestion** (consider): Style, naming, refactoring ideas, future improvements
   - **Already addressed**: Comments marked with "Addressed in commit" or similar

4. **For each actionable comment**, provide:
   - File and line reference
   - What the reviewer flagged
   - The suggested fix (code diff if provided by the reviewer)
   - Your assessment: agree, disagree with reason, or "style preference — skip"

5. **Output format**:

```
## PR #N Review Summary

### Critical (must fix)
1. **[file:line]** — [description]
   Fix: [what to change]

### Warning (should fix)
1. **[file:line]** — [description]
   Fix: [what to change]

### Suggestion (consider)
1. **[file:line]** — [description]
   Assessment: [agree/skip with reason]

### Already Addressed
- [description] — resolved in commit [hash]

### Skipped (style preferences)
- [description] — [why skipping]
```

## Important Notes

- Do NOT apply fixes automatically — present the summary for the user to decide
- Cross-reference suggestions with the project's CLAUDE.md coding standards
- If two reviewers flag the same issue, note the consensus
- Flag any suggestions that contradict the project's established patterns

### Handling Multi-Round Reviews

When a PR has been reviewed multiple times (e.g., after pushing fixes):
- Comments from earlier rounds may reference **code that no longer exists** (stale comments)
- Check if a comment's file path and line still match the current code
- Mark stale comments as "Already addressed" rather than re-flagging them
- Focus the summary on **genuinely new** comments from the latest review round
