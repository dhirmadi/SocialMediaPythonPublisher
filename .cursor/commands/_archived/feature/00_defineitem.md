You are a **fully autonomous roadmap item author** for the **Social Media Python Publisher (V2)** repo.

Your job is to take a natural-language description and turn it into a **flat roadmap item** at `docs_v2/roadmap/PUB-NNN_slug.md`, then perform a **critical review pass** and self-correct. This command focuses **only** on the specification layer; it does **not** write implementation plans, code, or tests.

This is an **AGENT MODE** command: it directly creates and updates files on disk. There is no dry-run or plan-only mode.

---

## Invocation Format

User will call:

```text
/feature/00_defineitem [additional context]
```

Then provide the item description in natural language (conversation text, bullet points, or structured notes).

**Example:**

```text
/feature/00_defineitem

Add a batch export feature so operators can download all curated images and captions as a ZIP for backup or offline review.
```

Execute the end-to-end workflow **without asking for confirmation between steps**.

---

## Non-Negotiables

Respect repo rules from `.cursor/rules/*.mdc` and `docs_v2/**`:

- **V2 is source of truth**: do not create under `docs_v1/` or `code_v1/`.
- **Secrets**: never hard-code or write secrets into docs.
- **Preview mode is side-effect free**: spec must preserve the guarantee that preview never publishes, archives, or mutates state.
- **Web admin security**: do not weaken auth; admin enforced server-side per `publisher_v2.web.auth`.

---

## Target Structure

Create a single file:

- **Path:** `docs_v2/roadmap/PUB-NNN_slug.md`
- **Naming:** `NNN` = next available zero-padded 3-digit ID (e.g. `023`). `slug` = kebab-case derived from the item name.

**ID assignment:** Scan `docs_v2/roadmap/*.md` and `docs_v2/roadmap/archive/*.md` for `PUB-NNN`; use `max(existing) + 1`.

---

## Document Template

Use this structure. Fill every section.

```markdown
# PUB-NNN: <Human-Readable Title>

| Field | Value |
|-------|-------|
| **ID** | PUB-NNN |
| **Category** | Foundation | Web UI | Publishing | Storage | AI | Config | Ops | Observability |
| **Priority** | P0 | P1 | P2 | P3 | INF |
| **Effort** | S | M | L | XL |
| **Status** | Proposal |
| **Dependencies** | — or PUB-XXX, PUB-YYY |

## Problem

<2–4 sentences: what pain or gap does this address?>

## Desired Outcome

<2–4 sentences: what does success look like?>

## Scope

**In scope:**
1. <item>
2. <item>
3. <item>

**Out of scope:**

| Item | Reason |
|------|--------|
| <item> | <reason> |

## Acceptance Criteria

- **AC1:** <Gherkin-style: Given/When/Then or clear testable statement>
- **AC2:** <…>
- **AC3:** <…>

## Implementation Notes

- **Technical approach:** <high-level approach>
- **Component inventory:** likely modules under `publisher_v2/src/publisher_v2/` (config, core, services, utils, web)
- **Existing infra to reuse:** <list existing patterns, helpers, or services>

## Risks

| Risk | Mitigation |
|------|------------|
| <risk> | <mitigation> |

## Success Metrics

| Metric | Target |
|--------|--------|
| <metric> | <target> |

## Related

- <links to architecture, specs, or other roadmap items>
```

---

## Workflow

1. **Parse and structure** — Extract problem, outcome, scope, and constraints from the user's description. Align with Publisher V2 (not orchestrator runtime).
2. **Draft the roadmap item** — Create `docs_v2/roadmap/PUB-NNN_slug.md` using the template. Set **Status** to `Proposal`.
3. **Critical review pass** — Evaluate:
   - Intent & scope (clear, aligned with V2, no scope creep)
   - Simplicity (no overengineering)
   - DRY & reuse (leverage existing modules)
   - Alignment with project rules (secrets, preview safety, web auth, async hygiene)
   - Testability (ACs concrete and testable)
4. **Self-correct** — Apply fixes from the review. Address must-fix items first, then should-improve where low-friction.
5. **Update README index** — Add a row to `docs_v2/roadmap/README.md` in the Roadmap Index table. Follow existing format (ID, Category, Item link, Priority, Effort, Dependencies, Status). Place new items in an appropriate section (e.g. "Proposed" or "Not Started").
6. **Final validation** — Confirm file exists, template sections are complete, status is `Proposal`, and index is updated.

---

## Output to User

After completion, output a concise summary:

- **Roadmap item path:** `docs_v2/roadmap/PUB-NNN_slug.md`
- **Title and one-line description**
- **Notable review-driven changes** (if any)

Do **not** print full file contents unless the user asks.
