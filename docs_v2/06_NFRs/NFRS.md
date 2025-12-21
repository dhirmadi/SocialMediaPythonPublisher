# Non‑Functional Requirements — Social Media Publisher V2

Version: 2.1  
Last Updated: December 21, 2025

## 1. Performance

| Metric | Target | Measured (as of latest report) |
|--------|--------|--------------------------------|
| E2E latency per post | < 30s | TBD (use telemetry logs) |
| Caption generation | < 3s | TBD (use telemetry logs) |
| Parallel platform publish | < 10s | TBD (use telemetry logs) |
| Test execution time | < 30s | ~25s (`docs_v2/10_Testing/TEST_EXECUTION_REPORT_2025-12-21.md`) |

- Telemetry-backed timings: key workflow stages and major web endpoints emit `*_ms` duration fields and `correlation_id` via `log_json` to support latency analysis.

## 2. Reliability
- Retries with exponential backoff on transient errors (tenacity decorators)
- Any‑success archive policy; partial failures recorded
- Graceful degradation on non-critical failures

## 3. Security
- Zero secrets in logs or VCS (regex redaction patterns)
- Sessions encrypted at rest (if stored)
- Temp file permissions: 0600 (owner-only)

## 4. Maintainability

| Metric | Target | Measured (as of latest report) |
|--------|--------|---------|
| Overall test coverage | ≥ 85% | 92% (`docs_v2/10_Testing/TEST_EXECUTION_REPORT_2025-12-21.md`) |
| Core module coverage | ≥ 90% | TBD (derive from coverage report by category) |
| Services coverage | ≥ 85% | TBD (derive from coverage report by category) |
| Web layer coverage | ≥ 85% | TBD (derive from coverage report by category) |
| Test pass rate | 100% | 100% (273/273) |
| Test warnings | 0 | 0 |
| Test count | Growing | 273 |

- Lint, type check clean
- Modular, pluggable publishers
- DRY compliance: no duplicate class definitions (target: 0)

## 5. Operability
- Structured JSON logs via `log_json()`
- Correlation IDs on all workflow operations
- Simple CLI with `--help` documentation
- Clear error messages with actionable context

## 6. Quality Metrics Reference

For detailed quality standards, thresholds, and measurement commands, see:
- `docs_v2/09_Reviews/QUALITY_METRICS.md` — Single source of truth for all quality targets
- `docs_v2/10_Testing/README.md` — Test documentation and commands


