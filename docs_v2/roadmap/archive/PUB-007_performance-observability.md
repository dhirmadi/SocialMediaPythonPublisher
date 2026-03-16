# PUB-007: Cross-Cutting Performance & Observability

| Field | Value |
|-------|-------|
| **ID** | PUB-007 |
| **Category** | Observability |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | — |

## Problem

Current logging and metrics are focused on correctness and error reporting, but they do not consistently capture per-stage timings or cross-cutting performance data. As more features (captionfile, expanded analysis, web interface) are added, it becomes difficult to pinpoint which stages are responsible for latency and to validate that the system meets its performance targets. There is no single feature-level specification that defines what performance telemetry must exist and how it should be used.

## Desired Outcome

A unified performance and observability layer across the V2 system that standardizes how timings, correlation IDs, and key metrics are captured. Operators can quickly see where a slow run spends time (Dropbox vs. OpenAI vs. publishers), and maintainers have a consistent pattern for adding and interpreting timing logs for new features.

## Scope

- Common pattern for measuring and logging timings across key stages (selection, analysis, captioning, sidecar write, publish, archive, web endpoints)
- Correlation IDs tying all logs for a single workflow run or web request together
- Standardized telemetry fields: `correlation_id`, `dropbox_list_images_ms`, `image_selection_ms`, `vision_analysis_ms`, `caption_generation_ms`, `sidecar_write_ms`, `publish_parallel_ms`, `archive_ms`, `web_random_image_ms`, `web_analyze_ms`, `web_publish_ms`
- Implementation using existing `utils.logging.log_json` and standard library timing
- Documentation for operators on where to look for performance data in logs

## Acceptance Criteria

- AC1: Given a typical CLI workflow run, when it completes, logs include timings for major stages (selection, analysis, captioning, sidecar write, publish, archive) and a correlation ID
- AC2: Given a call to any major web endpoint, when the request completes, logs include endpoint-level timing and a correlation ID
- AC3: Given representative test runs, when logs are sampled, timing/correlation fields are consistent and parseable for automated analysis
- AC4: New feature work touching performance-sensitive paths must adhere to the standardized telemetry patterns

## Implementation Notes

- Telemetry implemented via existing logging utilities; no new observability stack
- Telemetry overhead kept low (microseconds to low milliseconds per stage)
- No secrets, PII, or sensitive content in telemetry; only identifiers, timings, and high-level statuses
- Standard Telemetry Field Glossary documented for `correlation_id` and per-stage `*_ms` fields

## Related

- [Original feature doc](../../08_Epics/003_runtime_controls_telemetry/007_cross_cutting_performance_observability/007_feature.md) — full historical detail
