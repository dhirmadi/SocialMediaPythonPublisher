You are the **Product Manager Agent** generating a **status dashboard** for the Social Media Python Publisher V2.

## Task

Produce a flat status dashboard showing the current state of every roadmap item in `docs_v2/roadmap/` and `docs_v2/roadmap/archive/`.

## Process

1. **Scan active items** — all `PUB-NNN*.md` files under `docs_v2/roadmap/` (exclude README.md)
2. **Scan archived items** — all `PUB-NNN*.md` files under `docs_v2/roadmap/archive/`
3. **For each item, extract:**
   - Item ID (PUB-NNN)
   - Slug/name
   - Status (from **Status:** line)
   - Category (from **Category:**)
   - Priority (from **Priority:**)
   - Effort (from **Effort:**)
4. **Check for handoff** — does `PUB-NNN_handoff.md` exist (sibling of the item)?
5. **Cross-reference with test reports** — scan `docs_v2/10_Testing/` for any reports referencing item IDs
6. **Cross-reference with reviews** — scan `docs_v2/09_Reviews/` for any review docs referencing item IDs

### Output Format

    # Status Dashboard — Social Media Publisher V2
    Generated: <today's date>

    ## Executive Summary
    - Total items: N (Active: N | Archived: N)
    - By status: Done N | In Progress N | Not Started N | Proposal N | Deferred N | Superseded N
    - By category: <count per category>

    ## By Category

    | Category | ID | Item | Status | Priority | Handoff | Tests | Review |
    |----------|-----|------|--------|----------|---------|-------|--------|
    | Foundation | PUB-001 | slug | Done | P0 | ✅ | ✅ | ✅ |
    | Foundation | PUB-002 | slug | In Progress | P1 | ✅ | ⚠️ | — |
    | Web UI | PUB-003 | slug | Not Started | P2 | — | — | — |
    | ... | ... | ... | ... | ... | ... | ... | ... |

    Legend:
    - Handoff: ✅ = PUB-NNN_handoff.md exists, — = missing
    - Tests: ✅ = test report exists, ⚠️ = partial, — = no report
    - Review: ✅ = review doc exists, — = no review

    ## By Status

    | Status | Count | Items |
    |--------|-------|-------|
    | Done | N | PUB-001, PUB-005, ... |
    | In Progress | N | PUB-002, ... |
    | Not Started | N | PUB-003, ... |
    | Proposal | N | PUB-004, ... |
    | Deferred | N | ... |
    | Superseded | N | ... |

    ## Stale Items (no activity, status unclear)
    | Item | Path | Last Known Status | Issue |
    |------|------|-------------------|-------|
    | ... | ... | ... | ... |

    ## Action Items
    - Items needing attention (blocked, stale, or missing artifacts)
    - Recommended next steps

## Rules

- This command is **read-only** — do not modify any files
- Base all statuses on actual **Status:** lines in the documents
- If a document lacks a status field, mark it as Unknown and flag it
- Keep the output scannable — use tables, not prose
- Include both active and archived items in the counts; archived items are typically Done
