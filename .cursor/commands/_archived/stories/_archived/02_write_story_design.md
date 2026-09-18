Act as a **senior software architect**. Produce a complete **Story Design** document.

---

## Folder Structure

Story designs are stored at:
```
docs_v2/08_Features/NNN_feature_name/stories/SS_story_name/NNN_SS_design.md
```

Where:
- `NNN` = 3-digit feature ID
- `SS` = 2-digit story sequence number
- `story_name` = kebab-case or snake_case name

---

## Inputs

- Story definition file: `NNN_SS_story-name.md` (provided via @file)
- Parent feature design: `NNN_design.md` (in feature root)
- Optional: parent feature request

---

## Process

1. Read story definition completely
2. Read parent feature design for context
3. Extract: scope, acceptance criteria, dependencies
4. Define delta architecture (only what changes)
5. Specify component changes, data/contract updates
6. Detail implementation approach
7. Outline testing strategy for this story
8. Identify risks specific to this story

---

## Output

Produce **only** the Markdown file content.

Include the file path on the first line as an HTML comment.

---

## Document Structure

```markdown
<!-- docs_v2/08_Features/NNN_feature_name/stories/SS_story_name/NNN_SS_design.md -->

# <Story Name> — Story Design

**Feature ID:** NNN
**Story ID:** NNN-SS
**Parent Feature:** feature_name
**Design Version:** 1.0
**Date:** YYYY-MM-DD
**Status:** Design Review
**Author:** <infer or TODO>
**Story Definition:** NNN_SS_story-name.md
**Parent Feature Design:** ../../NNN_design.md

## 1. Summary
- What this story implements
- Goals & Non-goals (scoped to this story)

## 2. Context & Assumptions
- Current behavior (affected parts only)
- Constraints from parent feature
- Dependencies on other stories or systems

## 3. Requirements
### 3.1 Functional Requirements
- **SR1:** <requirement>
- **SR2:** <requirement>
### 3.2 Non-Functional Requirements
- <perf, security, observability impacts>

## 4. Architecture & Design (Delta)
### 4.1 Current vs. Proposed
- Current flow in affected area
- New behavior this story introduces
### 4.2 Components & Responsibilities
Only components touched by this story:
- `<Module>` — <what changes>
### 4.3 Data & Contracts
- New/changed schemas or API shapes
### 4.4 Error Handling & Edge Cases
- How errors are surfaced
- Important edge cases
### 4.5 Security, Privacy, Compliance
- Auth/access rules impacted

## 5. Detailed Flow
- Step-by-step sequence for main success path
- Key edge case flows

## 6. Testing Strategy
### 6.1 Unit Tests
- `<module>` — test <behavior>
### 6.2 Integration Tests
- Test <integration point>
### 6.3 E2E / Manual Tests
- Mapped to acceptance criteria from story definition

## 7. Risks & Alternatives
- Risks specific to this story with mitigations
- Alternatives considered (brief)

## 8. Work Plan
High-level implementation tasks:
1. <task>
2. <task>
3. <task>
...

**Definition of Done:**
- [ ] All functional requirements implemented
- [ ] All tests passing
- [ ] Documentation updated
- [ ] Code reviewed
```

---

## Rules

- Focus on **delta design** — don't redefine the entire feature
- Keep language concise and implementation-ready
- If information is missing, propose defaults and label as assumptions
- Do not contradict parent feature design; call out conflicts in Risks
- Output only Markdown content (no code fences around entire output)

---

## Start

Read story definition and parent feature design → generate story design → output only Markdown.

