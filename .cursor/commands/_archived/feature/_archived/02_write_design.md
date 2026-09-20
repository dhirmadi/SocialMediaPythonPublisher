Act as a **senior software architect**. Produce a complete **Feature Design** document.

---

## Folder Structure

Feature designs are stored at:
```
docs_v2/08_Epics/NNN_feature_name/NNN_design.md
```

---

## Inputs

- Feature request file: `NNN_feature.md` (provided via @file or context)
- Optional: existing system documentation

---

## Process

1. Read feature request end-to-end
2. Extract: problem statement, business value, scope, stakeholders, assumptions
3. Define target user flow and success criteria
4. Establish architecture: current vs. proposed, components, data flow, error paths
5. Specify API/contract changes, storage impacts, migrations
6. Detail algorithms, AI/model interactions if any
7. Non-functional requirements: performance, security, observability
8. Risks & mitigations, alternatives considered
9. Rollout plan: feature flags, config, migration steps
10. Test strategy: unit, integration, e2e
11. **Derive stories**: Break down into implementation stories

---

## Output

Produce **only** the Markdown file content.

Include the file path on the first line as an HTML comment.

---

## Document Structure

```markdown
<!-- docs_v2/08_Epics/NNN_feature_name/NNN_design.md -->

# <Feature Name> — Feature Design

**Feature ID:** NNN
**Design Version:** 1.0
**Date:** YYYY-MM-DD
**Status:** Design Review
**Author:** <infer or TODO>
**Feature Request:** NNN_feature.md

## 1. Summary
- Problem, Goals, Non-goals

## 2. Context & Assumptions
- Current state, Constraints, Dependencies

## 3. Requirements
### 3.1 Functional Requirements
- **FR1:** <requirement>
- **FR2:** <requirement>
### 3.2 Non-Functional Requirements
- <perf, security, observability>

## 4. Architecture & Design
### 4.1 Proposed Architecture
- Component diagram description
### 4.2 Components & Responsibilities
- `<Module>` — <responsibility>
### 4.3 Data Model / Schemas
- Before/after schemas
### 4.4 API/Contracts
- Request/response shapes, versioning
### 4.5 Error Handling & Retries
- Error paths, retry logic
### 4.6 Security, Privacy, Compliance
- Auth, sensitive data

## 5. Detailed Flow
- Sequence of operations
- Edge cases

## 6. Rollout & Ops
- Feature flags, Config
- Migration/Backfill plan
- Monitoring, Dashboards, Alerts
- Capacity/Cost estimates

## 7. Testing Strategy
- Unit, Integration, E2E, Performance
- Test cases mapped to acceptance criteria

## 8. Risks & Alternatives
- Risks with mitigations
- Alternatives considered

## 9. Work Plan
- Milestones, Tasks, Owners
- Definition of Done

## 10. Derived Stories

Break the feature into implementable stories:

| Story | Name | Scope | Dependencies |
|-------|------|-------|--------------|
| 01 | implementation | Core feature implementation | None |
| 02 | <name> | <scope> | 01 |
| 03 | <name> | <scope> | 01, 02 |

Each story should be:
- Small enough to implement in 1-3 sessions
- Independently testable
- Clearly scoped with defined acceptance criteria
```

---

## Rules

- Keep backward compatibility unless explicitly requested otherwise
- Call out assumptions and open questions clearly
- If information is missing, propose sensible defaults and highlight them
- Use concise, implementation-ready language
- Stories in §10 must together fully implement the feature

---

## Start

Read feature request → perform analysis → generate design with derived stories → output only Markdown.
