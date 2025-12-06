<!-- docs_v2/08_Features/08_04_ChangeRequests/003/002_preview-verbosity-controls.md -->

# Preview Verbosity Controls — Change Request

**Feature ID:** 003  
**Change ID:** 003-002  
**Name:** preview-verbosity-controls  
**Status:** Proposed  
**Date:** 2025-11-20  
**Author:** Architecture Team  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/003_expanded-vision-analysis-json_design.md  

## Summary
This change introduces configurable verbosity controls for how expanded vision analysis fields are rendered in CLI preview output.  
It allows operators to choose between a compact view and a detailed view of the optional analysis fields, without changing the underlying JSON structure or AI prompts.  
The goal is to keep previews readable and ergonomic while still making rich metadata available when desired.

## Problem Statement
As the set of analysis fields grows, the CLI preview output can become cluttered and harder to scan, especially for quick “is this safe to post?” checks.  
The existing design mentions potential verbosity controls but does not specify concrete behavior, configuration, or testable criteria.  
Without a standard approach, future additions to the analysis schema risk further degrading preview usability.

## Goals
- Provide a clear, configurable way to toggle between compact and detailed preview output for expanded analysis fields.  
- Preserve access to all analysis fields without overwhelming users with information in the default view.  
- Ensure that verbosity behavior is documented, testable, and consistent across runs.

## Non-Goals
- Changing any analysis JSON field names, semantics, or AI prompt behavior.  
- Introducing new CLI flags beyond what is reasonable and documented for preview flows.  
- Controlling how the web UI displays analysis data (that is handled by web-specific features).

## Affected Feature & Context
- **Parent Feature:** Expanded Vision Analysis JSON  
- **Relevant Sections:**  
  - §3. Requirements – printing optional fields in preview.  
  - §4. Architecture & Design – `utils/preview.print_vision_analysis`.  
  - §6. Rollout & Ops – mention of potential verbosity flags.  
- This change adds a small configuration and/or CLI hook and corresponding behavior in the preview utilities to selectively include or summarize optional fields while leaving the underlying analysis model unchanged.

## User Stories
- As an operator running `--preview`, I want a concise view of the most important analysis fields by default, so that I can quickly decide whether an image is appropriate to post.  
- As a power user, I want the option to see all expanded analysis fields in detail when needed, so that I can inspect metadata for training or curation purposes.  
- As a maintainer, I want preview verbosity behavior to be well-defined and tested, so that new fields can be added without unexpectedly cluttering the default output.

## Acceptance Criteria (BDD-style)
- Given an image is analyzed and `--preview` is run with default settings, when the preview output is printed, then only the core and a small, curated subset of optional fields should be displayed in a compact, readable format.  
- Given an image is analyzed and `--preview` is run with a high-verbosity option (e.g., config or flag), when the preview output is printed, then all available expanded analysis fields should be shown with clear labels.  
- Given no verbosity-related configuration is set, when `--preview` is executed, then behavior must match the documented default (e.g., compact mode) across runs.  
- Given new optional fields are added to `ImageAnalysis`, when preview is run, then tests must verify they are either included or intentionally summarized/omitted according to the verbosity rules.

## UX / UI Requirements
- CLI preview output must remain line-oriented and readable in standard terminal widths.  
- Verbosity toggles (flag names, config keys) must be self-explanatory and documented in CLI help and relevant docs.  
- Any additional labels or headings added for detailed mode should be consistent with existing preview style and avoid excessive color or formatting.

## Technical Notes & Constraints
- Implement verbosity behavior primarily in `utils/preview.print_vision_analysis`, driven by either a configuration value (e.g., `preview_verbosity`) or a CLI flag that maps into config.  
- Default behavior should favor compact output, with an explicit opt-in for full detail.  
- No changes may be made that affect serialization of `ImageAnalysis` or its internal representation.  
- The implementation must remain compatible with Python 3.9–3.12 and respect existing dry/preview semantics.

## Risks & Mitigations
- Too many modes could confuse users — Mitigation: start with only two levels (compact and detailed) and document them clearly.  
- Inconsistent handling of new fields could reintroduce clutter — Mitigation: define guidelines and tests for how new fields are rendered under each verbosity level.  
- CLI flag/config proliferation — Mitigation: reuse existing config mechanisms and avoid adding more than one new option if possible.

## Open Questions
- Should verbosity be controlled solely via config, solely via CLI flags, or a combination? — Proposed answer: allow both, with CLI overriding config.  
- What exact subset of fields should be shown in compact mode vs. detailed mode? — Proposed answer: TODO; decide based on current user workflows and feedback.  
- Do we need different verbosity defaults for different environments (e.g., dev vs. production)? — Proposed answer: TODO; likely not initially.


