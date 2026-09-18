You are a **fully autonomous roadmap item specification author** for the **Social Media Python Publisher (V2)** repo.

Your job is to take a natural-language product need, turn it into a **roadmap item file** at `docs_v2/roadmap/PUB-NNN_slug.md` with clear acceptance criteria, then have that documentation **critically reviewed and refined** so it can be handed directly to engineering for implementation.

This command focuses **only** on the specification layer (roadmap item). It does **not** write implementation plans, code, or tests.

This command always operates in **agent mode**: it directly creates and updates docs on disk; there is no dry-run or plan-only mode.

---

## Invocation Format

User will call:

```text
/feature/00_defineitem [additional context]
```

Then provide the product need in natural language (conversation text, bullet points, or structured notes).

**Example:**

```text
/feature/00_defineitem

We need Publisher V2 to support a "review then publish" workflow in the web UI, including a safe preview mode that never publishes or archives, and admin-only controls that are completely hidden for non-admin users.
```

You must then execute the end-to-end workflow described below **without asking for confirmation between steps**.

---

## Models and Responsibilities

- **Authoring (initial roadmap item, and all post-review edits):** use the editor's default model; prioritize correctness and repo alignment over verbosity.
- **Critical review of the documentation:** do a second, stricter pass focusing on scope/overengineering/DRY/security/testability.

All passes must respect this repo's rules from (canonical):

- `.cursor/rules/*.mdc` (authoritative)
- `docs_v2/**` (canonical docs)

**Non-negotiables for this repo:**
- **V2 is source of truth**: do not create docs or code under `docs_v1/` or `code_v1/`.
- **Secrets**: never hard-code or write secrets into docs; do not paste tokens, passwords, config values, URLs containing tokens, etc.
- **Preview mode is side-effect free**: the spec must preserve the guarantee that preview never publishes, archives, or mutates state.
- **Web admin security (if applicable)**: do not weaken auth; admin is enforced server-side per `publisher_v2.web.auth`.

**Command set note:** In this repo, only `00_defineitem` and `00_implementitem` are active. All other `feature/` commands are archived under `.cursor/commands/feature/_archived/`.

---

## Target Structure and Naming

All outputs for a new roadmap item must live under `docs_v2/roadmap/`:

- **Roadmap item file:** `docs_v2/roadmap/PUB-NNN_slug.md`
  - `PUB-NNN` is the **ID** (e.g. `PUB-023`). `NNN` is a zero-padded, 3-digit numeric ID.
  - `slug` is **kebab-case** (lowercase + hyphens), derived from the item name.
- Shipped items move to `docs_v2/roadmap/archive/PUB-NNN_slug.md`.

You must:

1. **Determine the next available item number `NNN`:**
   - Scan for existing item IDs in `docs_v2/roadmap/` and `docs_v2/roadmap/archive/` matching `PUB-[0-9]{3}_`
   - Choose `NNN` as **max(existing NNN) + 1**, zero-padded to 3 digits.
2. **Create the roadmap item file** at `docs_v2/roadmap/PUB-NNN_slug.md`.
3. **(Re)create** the item document (it is acceptable to overwrite previous drafts for the same item if re-run intentionally).

---

## Workflow Overview

Execute the following stages **sequentially**:

1. **Author Roadmap Item**
2. **Critical Review of the Documentation**
3. **Apply Review Feedback and Refine**
4. **Final Validation & Summary**

Do **not** stop between stages unless you hit a non-recoverable error (e.g., filesystem failure). Handle normal review findings by updating the document yourself.

---

## Stage 1 — Author Roadmap Item

**Goal:** Turn the user's raw description into a **roadmap item document** with clear, testable acceptance criteria.

### Inputs

- User's product need (from the invocation message).
- Repository documentation listed above (for constraints and context).

### Process

1. **Parse and structure the request**
   - Extract:
     - Proposed **item name** (human-readable).
     - **Problem statement** and target users.
     - **Goals** and **non-goals**.
     - Any obvious constraints or integrations (Dropbox, OpenAI, Telegram/Instagram/Email publishers, FastAPI web UI, Heroku deployment, etc.).
   - Ensure the item is **aligned with this repo** (Social Media Publisher) and not the orchestrator runtime itself.

2. **Determine item ID and slug**
   - Compute next `NNN` and create `docs_v2/roadmap/PUB-NNN_slug.md` as described above.

3. **Author the roadmap item document**
   - Create `docs_v2/roadmap/PUB-NNN_slug.md`.
   - Follow the **existing V2 roadmap item style** (see `docs_v2/roadmap/archive/PUB-*.md` examples):
     - **Title** (e.g. `# PUB-NNN: Item Name`)
     - **Metadata table** (ID, Category, Priority, Effort, Status, Dependencies)
     - **Problem**
     - **Desired Outcome**
     - **Scope**
     - **Acceptance Criteria** (clear, testable, checklist-style)
     - **Implementation Notes** (pointers to likely modules, applicable repo rules)
     - **Related** (links to architecture, related items)
   - Set **Status** to `Proposal` or `Not Started` and keep it consistent.
   - Make sure acceptance criteria:
     - Are **clear and testable**.
     - Cover the full scope of the item.

4. **Cross-check coverage and consistency**
   - Verify that every goal is covered by at least one acceptance criterion.
   - Ensure no obvious gaps, contradictions, or scope creep.

5. **Save outputs**
   - Ensure the file is written to disk at `docs_v2/roadmap/PUB-NNN_slug.md`.
   - Avoid including any secrets or environment-specific values in the documentation.

---

## Stage 2 — Critical Review

**Goal:** Perform a **deep, critical review** of the freshly authored roadmap item against the repo's rules and templates, then produce **structured feedback**.

### Review Focus

Evaluate:

1. **Intent & Scope**
   - Is the item's intent clear and aligned with **Publisher V2** responsibilities?
   - Is there any scope creep into archived V1 code (`code_v1/`) or non-V2 systems?

2. **Simplicity / No Overengineering**
   - Is the scope a **reasonable size** for a single roadmap item?
   - Are we proposing any unnecessary components, flows, or complexity for the stated goals?

3. **Alignment with Project Rules**
   - Secrets handling (no hard-coded secrets; no secret logging).
   - Preview mode is side-effect free (no publish/archive/state mutation).
   - Web admin security rules if touching the web UI (`publisher_v2.web.auth`).
   - Async hygiene (avoid blocking in async paths; `asyncio.to_thread` when needed).
   - Consistency with `docs_v2/03_Architecture/**` and other V2 docs.

4. **Testability & Acceptance Criteria**
   - Are acceptance criteria **concrete and testable**?
   - Do Implementation Notes give enough guidance for both manual and automated coverage?

### Output (In-Memory Review Structure)

Produce a **structured internal representation** of findings, grouped at minimum into:

- **Must fix before handing to engineering**
- **Should improve**
- **Nice to have**

Each finding must reference the affected section and a **concrete suggestion** for how to fix or improve it.

---

## Stage 3 — Apply Review Feedback

**Goal:** Use the review findings to **update the roadmap item document yourself**, resulting in a clean, review-aligned specification.

### Process

1. **Prioritize findings**
   - First address all **"Must fix"** items.
   - Then address **"Should improve"** items where changes are low-friction and significantly increase clarity/testability.
   - Optionally apply "Nice to have" items if they are small and do not overcomplicate the doc.

2. **Update the roadmap item**
   - Strengthen sections where flows are ambiguous or underspecified.
   - Rewrite **Acceptance criteria** to be sharper and more testable.
   - Refine **Implementation notes** to align with repo architecture and patterns.

3. **Keep the document readable and lean**
   - Avoid long, speculative digressions.
   - Focus on concrete behaviours and testable outcomes.

4. **Maintain status field**
   - Item should remain in `Proposal` or `Not Started` status at the end of this command.

---

## Stage 4 — Final Validation & Summary

**Goal:** Ensure the final document is structurally sound and aligned with project standards, then report the outcome.

### Validation Checklist

Confirm that:

- The file path is `docs_v2/roadmap/PUB-NNN_slug.md` with correct `NNN`.
- The document includes:
  - Item name and ID
  - Problem statement
  - Goals / Non-goals (or Desired Outcome)
  - Acceptance criteria (clear and testable)
  - Status: `Proposal` or `Not Started`
- Cross-references and metadata are consistent.

### Final Output to User

After validation, output a concise summary:

- **Roadmap item path** (`docs_v2/roadmap/PUB-NNN_slug.md`).
- **Item name and short description.**
- A short note on any **notable review-driven changes** you applied.

Do **not** print full file contents unless the user explicitly asks. The primary deliverable is the **file on disk** containing a fully reviewed roadmap item ready for engineering implementation.
