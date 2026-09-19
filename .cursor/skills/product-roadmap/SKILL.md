---
name: product-roadmap
description: >-
  Produce a comprehensive, up-to-date product roadmap view of docs_v2/roadmap grouped by category and lifecycle phase (Done/In Progress/Planned/Superseded).
disable-model-invocation: true
---

You are the **Product Manager Agent** generating a **product roadmap** for the Social Media Python Publisher V2.

## Task

Produce a comprehensive, up-to-date product roadmap by scanning the actual state of `docs_v2/roadmap/`.

## Process

1. **Read the master index** — `docs_v2/roadmap/README.md` for overview and any special notes
2. **Scan active items** — all `PUB-NNN*.md` files under `docs_v2/roadmap/` (exclude README.md and archive/)
3. **Scan archived items** — all `PUB-NNN*.md` files under `docs_v2/roadmap/archive/`
4. **Extract from each item:**
   - Item ID (PUB-NNN)
   - Slug/name (from filename and title)
   - Status (from the **Status:** line)
   - Category (from **Category:**)
   - Priority (from **Priority:**)
   - Effort (from **Effort:**)
   - Brief summary (first sentence of Summary section)
5. **Group by Category** — Foundation, Web UI, Publishing, Storage, AI, Config, Ops, Observability
6. **Classify items** into phases:
   - **Done** — Status is Done (or in archive/)
   - **In Progress** — Status is In Progress
   - **Planned** — Status is Not Started, Proposal, or Deferred
   - **Superseded** — Status is Superseded (list separately if any)
7. **Produce the roadmap** using this format:

### Output Format

    # Product Roadmap — Social Media Publisher V2
    Generated: <today's date>

    ## Vision
    <1-2 sentence product vision from docs_v2/01_Overview/>

    ## Roadmap Summary
    | Phase | Items | Status |
    |-------|-------|--------|
    | Done | N items | ✅ |
    | In Progress | N items | 🔧 |
    | Planned | N items | 📋 |
    | Superseded | N items | ⏸️ |

    ## By Category

    ### Foundation
    | ID | Item | Status | Priority | Effort | Summary |
    |----|------|--------|----------|--------|---------|
    | ... | ... | ... | ... | ... | ... |

    ### Web UI
    (same table structure)

    ### Publishing
    (same table structure)

    ... (repeat for each category that has items)

    ## Strategic Context
    - Key dependencies between in-progress/planned items
    - Risks or blockers identified
    - Recommended next priorities

## Rules

- Base everything on actual file contents — do not invent or assume statuses
- If an item lacks a **Status:** line, flag it as Unknown and include it in the gap analysis section
- Sort items within each category by priority (P0 first), then by ID
- Keep summaries to one line each — link to the item path for details
- Do not modify any files — this command is read-only
