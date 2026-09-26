# PUB-069: Single Source of Truth for the pip-audit Version Pin

| Field | Value |
|-------|-------|
| **ID** | PUB-069 |
| **Category** | Ops |
| **Priority** | P3 |
| **Effort** | XS |
| **Status** | Proposal |
| **Dependencies** | PUB-055 (merged, #236) |

## Problem

PUB-055 pins the pip-audit tool version so the thing deciding pass/fail is not itself a mutable
reference. That pin, `pip-audit==2.10.1`, is now written in five places:

1. `.github/workflows/security-scan.yml` (the gate)
2. `Makefile` (`security:` target)
3. `SECURITY.md` (local reproduction)
4. `.github/DEVELOPMENT.md` (contributor docs)
5. `scripts/pip_audit_ignore.py` (module docstring usage example)

A bump is a five-site edit, and the failure mode of missing one is silent: CI and the local
reproduction would audit with different tool versions and could disagree, which is exactly the kind
of drift PUB-055 exists to remove.

## Desired Outcome

The version is declared once and the other sites derive from it, or drift is detected by a test.

## Scope

**In scope:** either a single declaration the workflow and Makefile both read, or — cheaper and
probably sufficient — a test asserting all five occurrences agree.

**Out of scope:** changing which tool runs, or how it is invoked.

## Acceptance Criteria

- AC1: A pytest function asserts every occurrence of a `pip-audit==<version>` spec in tracked files
  names the same version, and fails if any one drifts.
- AC2: Bumping the version in the canonical place (or in all places, if the test-only approach is
  chosen) leaves the suite green.

## Notes

The test-only approach is likely the better trade: a shared variable across a workflow, a Makefile
and a docstring needs indirection that costs more readability than the duplication does. Decide
during hardening.

## Related

- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243) · PUB-055 (#236)
