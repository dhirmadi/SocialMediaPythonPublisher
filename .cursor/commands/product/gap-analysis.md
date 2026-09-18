You are the **Product Manager Agent** running a **gap analysis** on the Social Media Python Publisher V2 product roadmap.

## Task

Systematically identify gaps, inconsistencies, and missing artifacts across roadmap items in `docs_v2/roadmap/` (flat model).

## Process

### 1. Structural completeness scan

For every roadmap item (`PUB-NNN_slug.md`) in `docs_v2/roadmap/*.md` and `docs_v2/roadmap/archive/*.md`, check:

**Required sections:**
- [ ] Has a header table with: ID, Category, Priority, Effort, Status, Dependencies
- [ ] Has a **Problem** section
- [ ] Has a **Desired Outcome** section
- [ ] Has a **Scope** section
- [ ] Has **Acceptance Criteria** (ACs)
- [ ] Has **Implementation Notes**

**File and naming:**
- [ ] Filename matches `PUB-NNN_slug.md` (ID in filename matches header table)
- [ ] Slug is kebab-case and descriptive

### 2. Status consistency check

- Items with `Status: Done` should be in `docs_v2/roadmap/archive/`
- Items with status other than `Done` should be in `docs_v2/roadmap/` (not archive)
- Status value must be one of: `Proposal`, `Not Started`, `In Progress`, `Done`, `Deferred`, `Superseded`
- Dependencies reference valid PUB-NNN IDs (no broken refs)

### 3. README index consistency

- [ ] Every item in `docs_v2/roadmap/*.md` and `docs_v2/roadmap/archive/*.md` is listed in `docs_v2/roadmap/README.md`
- [ ] README links point to correct paths (active vs archive)
- [ ] README table columns are complete (ID, Category, Item, Priority, Effort, Dependencies, Status)

### 4. Orphan detection

- [ ] Handoff docs (`PUB-NNN_handoff.md`) in `docs_v2/roadmap/` or `docs_v2/roadmap/archive/` have a matching `PUB-NNN_slug.md` item
- [ ] No roadmap item files without a corresponding README entry

### 5. Category and ID hygiene

- [ ] Category is one of: Foundation, Web UI, Publishing, Storage, AI, Config, Ops, Observability
- [ ] PUB-NNN IDs are globally unique
- [ ] Dependencies list only existing PUB-NNN IDs

### Output Format

```
# Gap Analysis — Social Media Publisher V2
Generated: <today's date>

## Summary
| Category | Issues Found |
|----------|-------------|
| Missing artifacts | N |
| Status inconsistencies | N |
| README/index gaps | N |
| Naming/format issues | N |
| Orphaned items | N |

## Critical Gaps (block delivery or cause confusion)
| Item | Path | Issue | Recommended Fix |
|------|------|-------|-----------------|
| ... | ... | ... | ... |

## Moderate Gaps (should fix for hygiene)
| Item | Path | Issue | Recommended Fix |
|------|------|-------|-----------------|
| ... | ... | ... | ... |

## Minor Gaps (nice to fix)
| Item | Path | Issue | Recommended Fix |
|------|------|-------|-----------------|
| ... | ... | ... | ... |

## Recommendations
- Prioritized list of actions to close the most impactful gaps
```

## Rules

- This command is **read-only** — do not modify any files
- Be thorough but focus on actionable findings
- Prioritize gaps that affect delivery confidence (missing ACs, status mismatches, items in wrong folder)
- Reference specific file paths so findings are immediately actionable
- Do not flag stylistic preferences — focus on structural and content gaps
