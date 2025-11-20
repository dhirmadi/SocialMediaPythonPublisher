<!-- docs_v2/08_Features/08_01_Feature_Request/007_cross-cutting-performance-observability.md -->

# Cross-Cutting Performance & Observability

**ID:** 007  
**Name:** cross-cutting-performance-observability  
**Status:** Proposed  
**Date:** 2025-11-20  
**Author:** Architecture Team  

## Summary
This feature introduces a unified performance and observability layer across the V2 system, covering CLI workflows, web endpoints, AI calls, and external integrations.  
It standardizes how timings, correlation IDs, and key metrics are captured, making it easier to understand where time is spent and to detect regressions relative to the documented NFRs.  
The goal is to provide a light but consistent performance telemetry model that other features and change requests can build on.

## Problem Statement
Current logging and metrics are focused on correctness and error reporting, but they do not consistently capture per-stage timings or cross-cutting performance data.  
As more features (captionfile, expanded analysis, web interface) are added, it becomes difficult to pinpoint which stages are responsible for latency and to validate that the system meets its performance targets.  
There is no single feature-level specification that defines what performance telemetry must exist and how it should be used.

## Goals
- Define a common pattern for measuring and logging timings across key stages (e.g., selection, analysis, captioning, sidecar write, publish, archive, web endpoints).  
- Ensure correlation IDs and structured logs make it easy to trace a single request or workflow run end-to-end.  
- Provide enough standardized telemetry to support performance baselining and ongoing regression detection without heavy new infrastructure.

## Non-Goals
- Introducing a full observability stack (metrics backend, tracing system) as part of this feature.  
- Changing existing functional behavior or API contracts solely for telemetry reasons.  
- Replacing feature-specific logging requirements (e.g., for captionfile or web) that are already captured in their own designs.

## Users & Stakeholders
- Primary users: Operators and maintainers monitoring performance and reliability of the system.  
- Stakeholders: Architecture team, developers working on core features, DevOps teams responsible for deployment and runtime health.

## User Stories
- As an operator, I want to quickly see where a slow run is spending time (e.g., Dropbox vs. OpenAI vs. publishers), so that I can prioritize optimization work.  
- As a maintainer, I want a consistent way to add and interpret timing logs for new features, so that I don’t have to invent telemetry patterns each time.  
- As an architect, I want a single reference document for cross-cutting performance and observability expectations, so that all teams align on how to measure success.

## Acceptance Criteria (BDD-style)
- Given a typical CLI workflow run, when it completes, then logs must include timings for the major stages (at minimum: selection, analysis, captioning, sidecar write, publish, archive) and a correlation ID tying them together.  
- Given a call to any major web endpoint (e.g., random image, analyze, publish), when the request completes, then logs must include endpoint-level timing and a correlation ID, following the common pattern.  
- Given representative test runs under normal conditions, when logs are sampled, then the presence and structure of timing/correlation fields must be consistent and parseable for automated analysis.  
- Given new feature work that touches performance-sensitive paths, when it is implemented, then it must adhere to the standardized telemetry patterns defined by this feature.

## UX / Content Requirements
- No direct user-facing UI changes are required; telemetry is primarily backend and log-focused.  
- Documentation should include a brief operator-oriented section explaining where to look for performance data in logs and how to interpret key fields.  
- Any example logs in documentation should be updated to include the new timing and correlation fields where applicable.

## Technical Constraints & Assumptions
- Telemetry must be implemented using existing logging utilities (e.g., `utils.logging.log_json`) and standard library timing facilities.  
- The system must remain compatible with Python 3.9–3.12 and avoid reliance on environment-specific tracing tools.  
- Telemetry overhead should be kept low enough that it does not materially impact performance itself.

## Dependencies & Integrations
- Existing logging system and structured log consumers (e.g., log aggregators, Heroku logs).  
- Feature-specific telemetry work for captionfile, expanded analysis, web interface, and others, which will build on this feature.  
- NFR definitions in `docs_v2/06_NFRs/NFRS.md` that describe overall latency and reliability targets.

## Data Model / Schema
- No new persistent data models are required, but log event schemas may be extended to include standardized fields (e.g., `*_ms` for durations, `correlation_id`).  
- Any schema changes for logs should be documented to ensure downstream tools can adapt.  
- Optional: a lightweight internal representation for performance snapshots (e.g., for tests) may be introduced if helpful.

## Security / Privacy / Compliance
- Telemetry must not log secrets, PII, or sensitive image content; only identifiers, timings, and high-level statuses.  
- Correlation IDs must not be derived from user-sensitive data.  
- Logging volume and content must remain compliant with existing security and privacy guidelines.

## Performance & SLOs
- Instrumentation must have negligible impact on runtime latency (e.g., microseconds to low milliseconds overhead per stage).  
- Feature should enable monitoring of existing SLOs (e.g., workflow E2E latency, web endpoint p95s) rather than redefine them.  
- Any additional SLOs introduced (e.g., for telemetry completeness) should be documented as TODO and validated in later work.

## Observability
- Metrics: TODO; at minimum, derive counts and latency distributions from logs for key stages.  
- Logs & events: standardized timing and correlation log entries for workflow stages and web endpoints.  
- Dashboards/alerts: TODO; may include simple charts for stage timings and error rates, based on existing log tools.

### Standard Telemetry Field Glossary

The following timing and correlation fields are recommended across the system (names may be extended with additional context where needed):

- `correlation_id`: string tying together all logs for a single workflow run or web request.  
- `dropbox_list_images_ms`: duration of listing images from Dropbox.  
- `image_selection_ms`: duration of selecting and preparing an image (including hashing/metadata).  
- `vision_analysis_ms`: duration of the OpenAI vision analysis call.  
- `caption_generation_ms`: duration of caption/SD caption generation.  
- `sidecar_write_ms`: duration of writing SD caption sidecar text and metadata.  
- `publish_parallel_ms`: total duration of the parallel publishing phase.  
- `archive_ms`: duration of archiving the image and related sidecars.  
- `web_random_image_ms`: total duration of the `/api/images/random` endpoint.  
- `web_analyze_ms`: total duration of the `/api/images/{filename}/analyze` endpoint.  
- `web_publish_ms`: total duration of the `/api/images/{filename}/publish` endpoint.

## Risks & Mitigations
- Over-instrumentation could make logs noisy and harder to read — Mitigation: focus on high-value timings and avoid duplicating or overly verbose entries.  
- Inconsistent adoption across modules could reduce the value of telemetry — Mitigation: document patterns clearly and add checks/tests where feasible.  
- Telemetry code paths might accidentally log sensitive data — Mitigation: review logging fields carefully and enforce existing redaction rules.

## Open Questions
- Do we need a minimal in-repo script or tool for summarizing performance from logs? — Proposed answer: likely yes; could be defined in a later change or appendix.  
- Should we define a strict log schema for performance events, or keep it flexible? — Proposed answer: start with a recommended schema and tighten as needed.  
- What level of granularity is appropriate for sub-stage timings (e.g., per-publisher vs. aggregate)? — Proposed answer: TODO; may depend on real-world debugging needs.

## Milestones
- M1: Define and document standardized telemetry fields and patterns for core workflow and web endpoints.  
- M2: Implement instrumentation in key modules (workflow, AI, storage, web) and validate via tests and sample logs.  
- M3: Create basic documentation and, optionally, a simple log-analysis script or recipe for operators.

## Definition of Done
- Telemetry patterns are documented and adopted in core modules, with tests ensuring presence and basic correctness.  
- Operators can use logs to reconstruct where time is spent in typical runs without code changes.  
- No regressions in existing behavior or performance attributable to telemetry overhead.  
- Documentation and examples are updated to reflect the new observability approach.

## Appendix: Source Synopsis
- Performance review highlighted the need for better insight into per-stage latency and cross-cutting performance behavior.  
- Existing features (captionfile, expanded analysis, web interface) added some observability, but without a shared, system-wide pattern.  
- This feature request consolidates those needs into a single, coherent performance and observability specification.


