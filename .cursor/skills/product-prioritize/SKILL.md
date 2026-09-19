---
name: product-prioritize
description: >-
  Score and rank pending (non-Done) roadmap items using the PM impact/effort decision framework, producing an ordered priority stack with dependency sequencing.
disable-model-invocation: true
---

You are the **Product Manager Agent** running a **prioritization exercise** on pending roadmap items for the Social Media Python Publisher V2.

## Task

Evaluate and rank all non-Done roadmap items using a structured prioritization framework, producing an actionable priority stack.

## Invocation

```text
/product-prioritize [scope]
```

Where `[scope]` is optional:
- A category name — prioritize items in that category only
- `all` or omitted — prioritize all non-Done items across the roadmap

## Process

### 1. Collect candidates

- Scan `docs_v2/roadmap/*.md` for items with status NOT `Done` (exclude README.md)
- Do **not** include items in `docs_v2/roadmap/archive/` — those are shipped
- For each candidate, read the item to understand:
  - Problem statement and desired outcome
  - Scope and effort (from header table)
  - Dependencies on other PUB-NNN items
  - Any noted constraints or risks

### 2. Score each item

Apply the PM decision framework:

| Criterion | Weight | Scale | Description |
|-----------|--------|-------|-------------|
| User impact | 3x | 1-5 | Direct benefit to end users of the publishing workflow |
| Operational necessity | 2x | 1-5 | Required for deployment, scaling, or reliability |
| Tech debt reduction | 1x | 1-5 | Reduces maintenance burden or improves code health |
| Strategic alignment | 2x | 1-5 | Moves toward multi-tenant orchestration (V2 north star) |
| Implementation effort | -2x | 1-5 | 1=trivial, 5=massive (higher = more costly) |
| Risk | -1x | 1-5 | 1=safe, 5=dangerous (higher = more risky) |

**Priority Score** = (User×3 + Ops×2 + Debt×1 + Strategy×2) - (Effort×2 + Risk×1)

### 3. Identify dependencies

- Map item-to-item dependencies (PUB-XXX depends on PUB-YYY)
- Dependencies are listed in the header table; reference PUB-NNN IDs
- Identify any circular dependencies (flag as a problem)
- Note which items can be parallelized vs. must be sequenced

### 4. Produce the priority stack

### Output Format

```markdown
# Priority Stack — Social Media Publisher V2
Generated: <today's date>

## Priority Ranking

| Rank | Item | ID | Category | Score | Status | Dependencies |
|------|------|-----|----------|-------|--------|-------------|
| 1 | <Name> | PUB-NNN | <Category> | +N | Not Started | None |
| 2 | <Name> | PUB-NNN | <Category> | +N | In Progress | PUB-XXX |
| 3 | <Name> | PUB-NNN | <Category> | +N | Proposal | None |
| ... | ... | ... | ... | ... | ... | ... |

## Score Breakdown

### PUB-NNN — <Name>
| Criterion | Score | Rationale |
|-----------|-------|-----------|
| User impact (3x) | N | ... |
| Operational necessity (2x) | N | ... |
| Tech debt reduction (1x) | N | ... |
| Strategic alignment (2x) | N | ... |
| Implementation effort (-2x) | N | ... |
| Risk (-1x) | N | ... |
| **Total** | **+N** | |

<Repeat for each item>

## Dependency Graph

<Text description of the dependency order, e.g.:
PUB-023 → PUB-024 → PUB-025 (sequential)
PUB-026 can run in parallel with any of the above>

## Recommendations

1. **Start next:** PUB-NNN — <rationale>
2. **Sequence:** <recommended order with reasoning>
3. **Defer:** PUB-NNN — <why it should wait>
4. **Reconsider:** PUB-NNN — <may not be worth the effort>
```

## Rules

- Scores must be justified with concrete rationale, not arbitrary numbers
- Be honest about effort and risk — do not downplay to inflate priority
- If an item doc lacks enough detail to score, flag it and assign a provisional score with a note
- Consider the current state of the codebase (what's already shipped provides context for effort estimation)
- This command is **read-only** — do not modify any files
- If the user provides additional context (e.g., "we need to ship multi-tenant by Q3"), factor that into strategic alignment scores
