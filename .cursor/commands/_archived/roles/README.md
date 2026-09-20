## Role commands — fully archived

**This directory is retired.** These role prompts predate, and partly conflict
with, the canonical two-tool lifecycle now documented in
`.cursor/commands/product/lifecycle.md` (Cursor: specs/review/deploy, Claude
Code: `/implement` + `/verify`). In particular `po.md` and `sw.md` had Cursor
itself authoring specs and writing implementation code, which the current
model splits across the two tools instead. `gh.md` is superseded by the
still-active `.cursor/commands/github/commit.md`; `he.md`'s Heroku guidance
now lives inline in `/product/deploy.md` and `/experts/heroku.md`.

Kept for historical reference only — do not use these as live guidance.

---

Use these role prompts when a conversation starts to drift or when starting a new role-specific chat.

### How to use

1. Start (or continue) a conversation.
2. Paste the full content of the relevant role command (or reference it explicitly).
3. Then give the task + the GitHub issue link (when applicable).

### Roles in this repo

- `pm.md` — Product Manager (roadmap ownership, prioritization, delivery tracking; see also `product/_agent.md` for full PM Agent with slash commands)
- `po.md` — Product Owner (roadmap items via `/feature/00_defineitem`)
- `qa.md` — Quality Engineer (review roadmap items/specs; findings only)
- `sw.md` — Software Engineer (implementation via `/feature/00_implementitem`)
- `te.md` — Test Engineer (verify code + staging; findings only)
- `gh.md` — GitHub Engineer (PRs/merges/Copilot review workflow; MCP-first)
- `he.md` — Heroku Engineer (staging/prod deploy checks and promotions; MCP-first)
- `cursor_engineer.md` — Cursor Engineer (owns `.cursor/` rules/commands/workflows)
- `docs.md` — Documentation Expert (owns `docs_v2/` consistency and updates)

### Global rule

If role instructions conflict with user instructions, **ask** for clarification before acting.
