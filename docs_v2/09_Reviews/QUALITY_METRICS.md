# Quality Metrics — Social Media Python Publisher V2

**Version:** 1.0  
**Last Updated:** December 21, 2025  
**Purpose:** Single source of truth for project quality standards

---

## Overview

This document defines the quality metrics, targets, and measurement methods for the Social Media Python Publisher V2 project. It serves as the reference for:

- Quality control reviews
- CI/CD pipeline thresholds
- Pull request acceptance criteria
- Sprint planning quality gates

---

## 1. Test Quality Metrics

### 1.1 Core Test Metrics

| Metric | Target | Threshold | Measurement Command |
|--------|--------|-----------|---------------------|
| **Test Pass Rate** | 100% | ≥100% (blocking) | `uv run pytest` |
| **Test Warnings** | 0 | 0 (blocking) | `uv run pytest 2>&1 \| grep -i warning` |
| **Test Execution Time** | <30s | <60s (non-blocking) | pytest duration output |
| **Test Count** | Growing | ≥273 | `uv run pytest --collect-only -q` |

### 1.2 Code Coverage Targets

| Module Category | Target | Threshold | Notes |
|-----------------|--------|-----------|-------|
| **Overall** | ≥85% | ≥80% (blocking) | All source files |
| **Core Domain** | ≥90% | ≥85% | `core/` directory |
| **Services** | ≥85% | ≥80% | `services/` directory |
| **Configuration** | ≥90% | ≥85% | `config/` directory |
| **Web Layer** | ≥85% | ≥80% | `web/` directory |
| **Utilities** | ≥90% | ≥85% | `utils/` directory |
| **CLI Entry** | ≥80% | ≥70% | `app.py` |

### 1.3 Coverage Measurement

```bash
# Full coverage report
uv run pytest --cov=publisher_v2/src/publisher_v2 --cov-report=term-missing

# HTML report for detailed analysis
uv run pytest --cov=publisher_v2/src/publisher_v2 --cov-report=html
open htmlcov/index.html

# Per-module coverage
uv run pytest --cov=publisher_v2/src/publisher_v2/core --cov-report=term
```

---

## 2. Code Quality Metrics

### 2.1 DRY Compliance

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Duplicate Class Definitions** | 0 | `grep -r "class <Name>" \| wc -l` |
| **Duplicate Functions (>10 lines)** | 0 | Manual review / SonarQube |
| **Code Clone Ratio** | <5% | Static analysis tools |

### 2.2 Type Safety

| Metric | Target | Threshold | Measurement |
|--------|--------|-----------|-------------|
| **Type Hint Coverage** | High | Medium | `mypy --strict` |
| **Pydantic Validation** | All config | All config | Config module review |
| **Type Errors** | 0 | 0 (blocking) | `mypy publisher_v2/src/` |

### 2.3 Complexity Metrics

| Metric | Target | Threshold | Notes |
|--------|--------|-----------|-------|
| **Max Function Length** | <50 lines | <100 lines | Per function |
| **Max Module Length** | <300 lines | <500 lines | Per file |
| **Cyclomatic Complexity** | <10 | <15 | Per function |
| **Max Nesting Depth** | ≤3 | ≤4 | Control structures |

### 2.4 Static Analysis

```bash
# Linting
uv run flake8 publisher_v2/src/

# Type checking
uv run mypy publisher_v2/src/publisher_v2/

# Code formatting verification
uv run black --check publisher_v2/
uv run isort --check publisher_v2/

# Security scanning
uv run bandit -r publisher_v2/src/
```

---

## 3. Runtime Quality Metrics

### 3.1 Performance

| Metric | Target | Threshold | Source |
|--------|--------|-----------|--------|
| **E2E Workflow Latency** | <30s | <60s | `workflow_timing` log |
| **Caption Generation** | <3s | <5s | `caption_generation_ms` |
| **Parallel Publish** | <10s | <15s | `publish_parallel_ms` |
| **Image Selection** | <5s | <10s | `image_selection_ms` |

### 3.2 Reliability

| Metric | Target | Notes |
|--------|--------|-------|
| **Retry Coverage** | 100% external calls | All APIs use tenacity |
| **Error Recovery** | Any-success policy | Partial failures acceptable |
| **Graceful Degradation** | Supported | Continue on non-critical failures |

### 3.3 Security

| Metric | Target | Verification |
|--------|--------|--------------|
| **Secrets in Logs** | 0 | Redaction pattern tests |
| **Secrets in VCS** | 0 | `.gitignore`, pre-commit hooks |
| **Temp File Permissions** | 0600 | Code review |

---

## 4. Documentation Quality

### 4.1 Required Documentation

| Document | Location | Update Frequency |
|----------|----------|------------------|
| Architecture | `docs_v2/03_Architecture/` | Major changes |
| Configuration | `docs_v2/05_Configuration/` | Config changes |
| NFRs | `docs_v2/06_NFRs/` | Quarterly |
| Features | `docs_v2/08_Features/` | Per feature |
| Reviews | `docs_v2/09_Reviews/` | Per review |
| Testing | `docs_v2/10_Testing/` | Test changes |

### 4.2 Documentation Standards

- All public APIs documented with docstrings
- All configuration options documented
- All CLI flags documented with `--help`
- Change requests include before/after examples

---

## 5. Test Infrastructure Quality

### 5.1 Fixture Management

| Metric | Target | Rationale |
|--------|--------|-----------|
| **Shared Fixtures** | All reusable mocks | DRY compliance |
| **Fixture Location** | `conftest.py` | Discoverability |
| **Fixture Documentation** | All fixtures | Maintainability |

### 5.2 Test Organization

| Directory | Purpose |
|-----------|---------|
| `tests/` | Unit tests (root) |
| `tests/web/` | Web layer unit tests |
| `tests/web_integration/` | Web integration tests |
| `tests/conftest.py` | Shared fixtures |

### 5.3 Test Naming

```
test_<action>_<expected_result>

Examples:
- test_config_loads_valid_ini
- test_workflow_skips_duplicate_images
- test_admin_endpoint_requires_auth
```

---

## 6. CI/CD Quality Gates

### 6.1 Pre-Merge Checks (Blocking)

| Check | Command | Threshold |
|-------|---------|-----------|
| Tests Pass | `uv run pytest` | 100% |
| Coverage | `--cov` | ≥80% overall |
| Lint | `uv run flake8` | 0 errors |
| Type Check | `uv run mypy` | 0 errors |
| Formatting | `uv run black --check` | Clean |

### 6.2 Post-Merge Checks (Non-Blocking)

| Check | Command | Target |
|-------|---------|--------|
| Coverage Report | HTML generation | Archive for trends |
| Security Scan | `bandit -r` | 0 high/critical |
| Dependency Audit | `safety check` | 0 vulnerabilities |

---

## 7. Quality Review Process

### 7.1 Review Types

| Type | Frequency | Trigger |
|------|-----------|---------|
| **QC Review** | Quarterly | Scheduled |
| **Feature Review** | Per feature | Feature completion |
| **Security Review** | Bi-annually | Scheduled |
| **Performance Review** | As needed | Performance issues |

### 7.2 Review Deliverables

Each QC review produces:

1. **Review Report** — `docs_v2/09_Reviews/QUALITY_CONTROL_REVIEW_<date>.md`
2. **Findings List** — Prioritized issues with IDs (QC-XXX)
3. **Action Items** — Assignable tasks with effort estimates
4. **Updated Metrics** — Current state vs targets

### 7.3 Finding Severity Levels

| Level | Definition | Response Time |
|-------|------------|---------------|
| **Critical** | Blocks production or causes data loss | Immediate |
| **High** | Violates quality target, affects reliability | Next sprint |
| **Medium** | Process improvement, documentation gap | 2 sprints |
| **Low** | Nice-to-have, minor improvement | Backlog |

---

## 8. Current Quality Status

### As of December 21, 2025

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Test Pass Rate | 100% | 100% | ✅ Met |
| Test Warnings | 0 | 0 | ✅ Met |
| Overall Coverage | ≥85% | 92% | ✅ Exceeded |
| Core Coverage | ≥90% | 96% | ✅ Exceeded |
| Services Coverage | ≥85% | 94% | ✅ Exceeded |
| Config Coverage | ≥90% | 97% | ✅ Exceeded |
| Web Coverage | ≥85% | 89% | ✅ Met |
| Utils Coverage | ≥90% | 96% | ✅ Exceeded |
| Test Execution | <30s | ~25s | ✅ Met |
| DRY Compliance | 0 dupes | 32 dupes | ⚠️ Below Target |

### Open Issues

| ID | Description | Severity | Status |
|----|-------------|----------|--------|
| QC-001 | Test fixture duplication | Critical | Open |
| QC-002 | storage.py coverage at 83% | High | Open |
| QC-003 | web/service.py coverage at 81% | High | Open |
| QC-004 | NFRs.md not updated | Medium | ✅ Resolved |
| QC-006 | No centralized quality metrics | Medium | ✅ Resolved |

---

## Appendix: Measurement Scripts

### Quick Quality Check

```bash
#!/bin/bash
# quick_quality_check.sh

cd /Users/evert/Documents/GitHub/SocialMediaPythonPublisher

echo "=== Test Pass Rate ==="
uv run pytest -q

echo "=== Coverage Summary ==="
uv run pytest --cov=publisher_v2/src/publisher_v2 --cov-report=term -q 2>&1 | tail -5

echo "=== DRY Check (Dummy Classes) ==="
grep -r "class Dummy" publisher_v2/tests/ | wc -l
echo "dummy class definitions found"

echo "=== Lint Check ==="
uv run flake8 publisher_v2/src/ --count --statistics 2>&1 | tail -3
```

### Full Quality Report

```bash
#!/bin/bash
# full_quality_report.sh

cd /Users/evert/Documents/GitHub/SocialMediaPythonPublisher

echo "Running comprehensive quality analysis..."

# Tests with full coverage
uv run pytest --cov=publisher_v2/src/publisher_v2 \
    --cov-report=term-missing \
    --cov-report=html \
    -v

# Static analysis
uv run flake8 publisher_v2/src/
uv run mypy publisher_v2/src/publisher_v2/ --ignore-missing-imports

# Security
uv run bandit -r publisher_v2/src/ -ll

echo "Reports generated. Open htmlcov/index.html for coverage details."
```

---

**Document Version:** 1.0  
**Last Reviewed:** December 21, 2025  
**Next Review:** March 2026  
**Maintainer:** QC Engineer

