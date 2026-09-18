## Feature workflow commands (V2) — fully archived

**This entire directory is retired.** It used to describe the "active canonical"
commands for this repo, but that changed: the canonical lifecycle is now owned by
`.cursor/commands/product/*` (Cursor: CREATE/HARDEN/REVIEW/DEPLOY/ARCHIVE) and
Claude Code's `/implement` + `/verify` (IMPLEMENT/VERIFY). See
`.cursor/commands/product/lifecycle.md` for the current model.

- `00_defineitem.md` is superseded by `/product/propose-item` + `/product/harden`.
- `00_implementitem.md` is superseded by Claude Code's `/implement` — it let Cursor
  itself write implementation code, which contradicts the two-tool split (Cursor
  specs, Claude Code implements) that the rest of this repo's docs assume.
- `_archived/*` (nested): the older Epics/Features/Stories model, archived before
  the flat roadmap model existed.

If you need to reference or restore anything here for a one-off workflow, copy it
back explicitly and document why — do not treat this directory as live guidance.
