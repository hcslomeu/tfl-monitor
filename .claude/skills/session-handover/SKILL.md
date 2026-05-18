---
name: session-handover
description: Generate a structured session-resume prompt before /clear or starting a fresh session. Use when the user wants to carry forward project state, pending work, active WP info, open AI-reviewer threads (Claude, Codex, CodeRabbit, Gemini), or session-specific knowledge into a new conversation. Triggers on phrases like "handover", "session handover", "resume prompt", "before I clear", "/handover", or any request to summarise current session state for continuation.
---

# Session Handover

Produce a self-contained prompt that the user can paste verbatim into a new
Claude Code session to resume work without losing context.

## When to invoke

- User explicitly asks for a "handover", "resume prompt", or similar before
  running `/clear`.
- User signals they're about to start a fresh session and need to carry state
  forward.
- After a major milestone (PR merge, WP completion) when the user is wrapping
  up a working block.

## Output rules

1. **Wrap the entire handover in a single fenced ```code block```** so the user
   can copy/paste it verbatim. Use Markdown headings inside the block.
2. **Language: English** — the handover represents persisted-state knowledge
   and may live in chat but mirrors what would otherwise sit in
   `.claude/*.md`. Even when the surrounding chat is PT-BR, the handover body
   is English.
3. **Self-contained** — assume the next session has zero context. Repeat the
   facts the next agent needs, even if they are "obvious" right now.
4. **Cap length at ~80 lines** unless the current session has unusually deep
   state (multi-PR, multi-WP, mid-incident, many open review threads).
5. **Use exact identifiers** — commit hashes, PR numbers, GitHub issue
   numbers, branch names, file paths, reviewer comment IDs. No vague
   references.
6. **Skip platform/environment boilerplate** (model name, OS, shell) — the
   next session resolves its own environment.
7. **After the fenced block**, surface pending uncommitted local changes with
   the exact `git` commands the user should run before clearing — easy to
   miss otherwise.

## Required sections (in order)

1. **Project context** — repo path; stack lock summary (one line); hard rules
   on language, commits, push policy, parallelism. Focus on the rules that
   would surprise a fresh session if violated.
2. **Bootstrap** — ordered list of files the next session must read first
   (typically `.claude/napkin.md` if it exists, then `PROGRESS.md`, then
   `.claude/current-wp.md`, then a skim of `CLAUDE.md` / `AGENTS.md`). If a
   PR is open, include the exact `gh pr view <num> --comments` and
   `gh api repos/<owner>/<repo>/pulls/<num>/comments` commands so the next
   session re-hydrates AI-reviewer state on demand.
3. **State** — last completed WP / PR (with hash and number); branches still
   open; pending uncommitted local changes; any session-only state that is
   not yet on disk.
4. **Active WP** — ID, track, GH issue #, dependencies, allowed-surface
   directories, acceptance-criteria summary. If no WP is active, say so
   explicitly.
5. **Pre-push verification gate** — exact commands the project uses, all four
   in one shell line if possible.
6. **Merge flow** — branch-protection / ruleset behaviour, expected
   re-review patterns from AI reviewers (Claude Code, Codex, CodeRabbit,
   Gemini Code Assist), and the exact merge command. Include
   thread-resolution gotchas if relevant (e.g. CodeRabbit needs every thread
   resolved; Claude/Codex inline comments do not block merge but should be
   triaged).
7. **Open review threads** — for each open PR, list unresolved comments from
   each AI reviewer that posted on this session's work:
   - **Reviewer** (Claude Code / Codex / CodeRabbit / Gemini)
   - **PR # and file:line**
   - **Ask** in one phrase
   - **Disposition**: accepted (with commit hash if fixed) / disputed (with
     one-line counter-argument so next session doesn't re-litigate) /
     pending (with planned action)
   Group by PR. If no open threads, say "No open review threads." explicitly
   so the next session doesn't go hunting.
8. **External system mapping** — Linear↔GitHub mapping, MCP availability
   notes, anything specific that the current session learned about external
   integrations.
9. **Parallelism** — current default (serial vs parallel teammates) plus any
   caveats discovered (worktree isolation gotchas, etc.).
10. **Immediate next action** — single concrete first step. Should be
    actionable in the first 30 seconds of the next session. If a review
    thread is the next action, name the reviewer + PR + file:line.

## Anti-patterns

- Don't include exploratory output, file dumps, or large code excerpts —
  reference paths instead.
- Don't paste full review-comment bodies — one-phrase ask + disposition only.
  The next session can run the `gh` commands from Bootstrap to fetch full
  text on demand.
- Don't restate generic CLAUDE.md content the next session will re-load on
  its own. Focus on session-specific deltas and active state.
- Don't paraphrase ADRs or specs already on disk; cite them by path.
- Don't include conversation chronology or "what we tried" narratives —
  handover is forward-looking state, not a session log.
- Don't add a "session summary" preamble in PT-BR before the fenced block;
  the user wants to copy/paste, not read narrative.

## Curation hint

If the current session uncovered a recurring lesson worth persisting beyond
the next session, suggest a napkin (`.claude/napkin.md`) update *separately*
from the handover — keep the handover focused on transient resume state, not
permanent runbook entries.

If a reviewer (Claude / Codex / CodeRabbit / Gemini) repeatedly flags the
same class of issue across PRs, that's a napkin candidate, not a handover
entry.
