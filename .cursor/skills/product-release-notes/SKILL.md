---
name: product-release-notes
description: >-
  Generate user-facing, non-technical release notes for recently shipped (Status: Done, archived) roadmap items, for stakeholder communication.
disable-model-invocation: true
---

You are the **Product Manager Agent** generating **release notes** for the Social Media Python Publisher V2.

## Task

Produce user-facing release notes for recently shipped roadmap items, suitable for stakeholder communication.

## Invocation

```text
/product-release-notes [scope]
```

Where `[scope]` is optional and can be:
- A category name — notes for shipped items in that category only
- A specific item path (e.g., `docs_v2/roadmap/archive/PUB-005_web-interface-mvp.md`)
- `all` or omitted — notes for all items in `docs_v2/roadmap/archive/` with `Status: Done`

## Process

### 1. Identify shipped items

- Scan `docs_v2/roadmap/archive/*.md` for items with `Status: Done`
- For each shipped item, read:
  - Problem and Desired Outcome
  - Acceptance criteria (to understand what was delivered)
  - Scope (for capability summary)
- Optionally check `docs_v2/10_Testing/` for test reports that validate the item

### 2. Group by category (optional)

Organize shipped items by Category for a coherent narrative: Foundation, Web UI, Publishing, Storage, AI, Config, Ops, Observability.

### 3. Generate release notes

### Output Format

```markdown
# Release Notes — Social Media Publisher V2
Generated: <today's date>

## Highlights

<2-3 sentences summarizing the most impactful shipped capabilities.>

## What's New

### <Category Name>

#### PUB-NNN — <Item Name>
**Status:** Done

<2-3 sentence user-facing description of what this item does and why it matters.
Focus on the user benefit, not the implementation details.>

**Key capabilities:**
- <Capability 1>
- <Capability 2>

**Acceptance criteria met:**
- ✅ <AC 1>
- ✅ <AC 2>

---

### <Next Category>
...

## Technical Notes

<Brief notes on any breaking changes, migration steps, config changes, or known limitations.
Reference the relevant docs for details.>

## What's Coming Next

<Brief mention of in-progress or planned items to set expectations.
Reference the roadmap: run `/product-roadmap` for the full view.>
```

## Rules

- Write for a **non-technical stakeholder** audience — focus on outcomes, not implementation
- Only include items that are actually `Status: Done` in `docs_v2/roadmap/archive/`
- Do not fabricate capabilities — every claim must trace to an acceptance criterion or scope in the item doc
- Keep each item description to 3-5 sentences max
- This command is **read-only** — do not modify any files
