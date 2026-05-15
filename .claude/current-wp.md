## Active work packages

| WP | Status | Notes |
|---|---|---|
| TM-D5 | Done ✅ 2026-05-08 | LangGraph agent (SQL + RAG) shipped, PR #44 merged |
| TM-E5 | Done ✅ 2026-05-12 | One-pager dashboard + chat. Three sub-PRs merged: #51 (hook + labels + primitives), #53 (6 cards + chat panel + about sheet), #54 (page rewrite + redirects + legacy deletion + AbortSignal/ApiError fixes). |
| TM-A5 | Blocked | Research + plan committed (PR #49). Blocked on Section 8 confirmation gate (AWS deploy decision). |
| TM-E4 | Done ✅ 2026-05-13 | Frontend migration + Vercel deploy. Phases 1–5 PRs #56–#60; Phase 6 layout fidelity #62; deploy live at `https://tfl-monitor.vercel.app` (target=production). Custom domain `tfl-monitor.humbertolomeu.com` attached on Vercel — pending CNAME add on Cloudflare (`tfl-monitor → cname.vercel-dns.com`, DNS only, no proxy). |
| TM-F2 | Done ✅ 2026-05-16 | Production wiring — frontend on real API. Backend CORS narrowed with apex + Vercel-preview regex; `USE_MOCKS` flipped to opt-in; Vercel env vars wired (`NEXT_PUBLIC_API_URL` set on both targets, `NEXT_PUBLIC_USE_MOCKS` unset); `ChatPanel` rewritten on top of `streamChat()` (5 RTL cases ported from TM-E3 `ChatView`); `MOCK_CHAT_SEED` + `lib/mocks/chat.ts` removed. Locked decisions in `.claude/specs/TM-F2-plan.md` §7: API hostname migration deferred; offline-dev short-circuits in `lib/api/{status-live,disruptions-recent}.ts` kept. |
