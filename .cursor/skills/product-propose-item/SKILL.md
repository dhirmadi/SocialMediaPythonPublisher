---
name: product-propose-item
description: >-
  Turn a described product need into a new, properly structured roadmap item at docs_v2/roadmap/PUB-NNN_slug.md, with overlap checking against existing items and impact/effort scoring.
disable-model-invocation: true
---

You are the **Product Manager Agent** proposing a **new roadmap item** for the Social Media Python Publisher V2.

## Task

Turn the user's product need into a properly structured roadmap item at `docs_v2/roadmap/PUB-NNN_slug.md`.

## Invocation

```text
/product-propose-item [description of the product need]
```

The user provides a natural-language description of the initiative. You produce the roadmap item file and update the index.

## Process

### 1. Discover the next item ID

- Scan `docs_v2/roadmap/` for files matching `PUB-NNN_*.md`
- Scan `docs_v2/roadmap/archive/` for files matching `PUB-NNN_*.md`
- Extract the highest NNN across both locations and increment by 1 (zero-padded to 3 digits)

### 2. Validate against existing items

- Read `docs_v2/roadmap/README.md` and existing item files to check for overlap
- If the proposed initiative overlaps significantly with an existing item, recommend extending that item instead of creating a new one
- Proceed with creation only if the initiative is clearly distinct

### 3. Derive slug from name

- Convert the human-readable name to a slug: lowercase, hyphens for spaces, alphanumeric + hyphens only
- Example: "Orchestrator Schema V2 Integration" → `orchestrator-schema-v2-integration`

### 4. Write the User Story

Phrase one `As a <role>, I want <capability>, so that <benefit>` sentence that frames the
item from the affected person's point of view before diving into Problem/Desired Outcome.
Pick the role by category:

| Category | Typical role |
|----------|-------------|
| Web UI | "admin" (the person operating the web UI) |
| Publishing | "publisher operator" (the person running the pipeline) |
| AI | "publisher operator curating content" (benefits from better captions/analysis) |
| Storage, Config, Ops, Observability, Foundation | "publisher operator" or "platform maintainer" |

If an item genuinely serves two distinct roles, add a second `As a ..., I want ..., so that
...` line rather than forcing one story to cover both.

### 5. Assess priority (impact/effort scoring)

Use the decision framework:

| Criterion | Score (1-5) | Notes |
|-----------|-------------|-------|
| User impact | N | Who benefits and how? |
| Operational necessity | N | Does it unblock or fix production? |
| Tech debt reduction | N | Does it improve maintainability? |
| Strategic alignment | N | Fits roadmap direction? |
| Effort estimate | N | 1=low, 5=high → map to S/M/L/XL |
| Risk | N | 1=low, 5=high |

**Priority score**: (impact sum) / (effort + risk). Higher score → higher priority. Map to P0/P1/P2/P3.

**Effort mapping**: S (<1 week), M (1-2 weeks), L (2-4 weeks), XL (1+ month).

### 6. Create the roadmap item file

Create `docs_v2/roadmap/PUB-NNN_slug.md` with this structure:

```markdown
# PUB-NNN: <Human-Readable Name>

| Field | Value |
|-------|-------|
| **ID** | PUB-NNN |
| **Category** | <Foundation|Web UI|Publishing|Storage|AI|Config|Ops|Observability> |
| **Priority** | <P0|P1|P2|P3|INF> |
| **Effort** | <S|M|L|XL> |
| **Status** | Proposal |
| **Dependencies** | — |

## User Story

As a <role>, I want <capability>, so that <benefit>.

## Problem

<What user/operational problem does this solve? Who is affected?>

## Desired Outcome

<Concrete, measurable outcome. What does success look like?>

## Scope

**In scope:**
- <Item 1>
- <Item 2>

**Out of scope:**
- <Item 1>
- <Item 2>

## Acceptance Criteria

- AC1: Given <precondition>, when <action>, then <observable outcome>
- AC2: Given <precondition>, when <action>, then <observable outcome>
- ...

## Implementation Notes

<Technical hints, module boundaries, dependencies. Optional at proposal stage.>

## Risks

<Key risks and mitigations. Optional.>

## Success Metrics

<How we measure success. Optional.>

## Related

- <Links to related items, docs, or external references. Optional.>
```

### 7. Update the roadmap index

Add the new item to `docs_v2/roadmap/README.md` in the Roadmap Index table, following the existing format:

```markdown
| PUB-NNN | <Category> | [<Name>](PUB-NNN_slug.md) | <Priority> | <Effort> | <Dependencies> | Proposal |
```

Place it in the appropriate section (active items before the "Shipped" sections, or in a new "Proposed" section if that exists).

### 8. Output summary

Report:
- Item file path: `docs_v2/roadmap/PUB-NNN_slug.md`
- Item ID and name
- Category, priority, effort
- Any overlap warnings with existing items
- Recommended next step: "Use `/product-harden docs_v2/roadmap/PUB-NNN_slug.md` to harden the spec for implementation"

## Rules

- Follow existing naming: file is `PUB-NNN_slug.md`, slug is lowercase-hyphenated
- Keep the item scoped — one cohesive deliverable, not a grab-bag
- Apply the decision framework honestly; do not inflate scores
- Status is always `Proposal` for new items
- Categories: Foundation, Web UI, Publishing, Storage, AI, Config, Ops, Observability
- Ensure applicable V2 constraints (preview safety, secrets, web auth, async hygiene) are reflected in Scope or ACs where relevant
