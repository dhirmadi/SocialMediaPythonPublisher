# PUB-067: SHA-Pin `code-quality.yml`

| Field | Value |
|-------|-------|
| **ID** | PUB-067 |
| **Category** | Ops |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-055 (merged, #236) |

## Problem

PUB-055 SHA-pinned every action in `security-scan.yml` and `secret-scan.yml`, scoped there because
those were the files its Problem section cited. `code-quality.yml` was explicitly out of scope and
is still **entirely tag-pinned, with zero SHA pins**.

That scoping is now the weaker half of the argument: since #229, `code-quality.yml` runs the
`pre-commit` job, which is where bandit, detect-secrets and gitleaks actually block. In substance it
is a security gate, and it is the one whose actions can still move underneath us. PUB-055's own
summary called it "the natural next place to apply the same policy".

`code-quality.yml:55` also still carries a comment describing the `bandit -r .` step that #236
deleted from `security-scan.yml`.

## Desired Outcome

Every `uses:` in `code-quality.yml` is pinned by 40-character commit SHA with the referenced tag in
a trailing comment, on the same terms PUB-055 established, and the stale comment is gone.

## Scope

**In scope:** SHA-pinning `code-quality.yml`; removing the stale line-55 comment; extending
`test_every_action_in_the_security_workflows_is_pinned_by_sha` (or a sibling) to cover this file.

**Out of scope:** bumping any action's major version while pinning — same rule PUB-055 followed;
`caption-eval-nightly.yml`, which documents its own tag-vs-SHA policy.

## Acceptance Criteria

- AC1: Every `uses:` value in `code-quality.yml` matches `<owner>/<repo>@<40-hex>` with a version
  comment on the same or next line, asserted by a pytest function named in this item's handoff.
- AC2: No comment in `code-quality.yml` describes a step that no longer exists.

## Notes

Reuse the helpers in `publisher_v2/tests/test_ci_security_gates.py` rather than duplicating the
parser — it already handles flow-style mappings and the comment requirement, and it was hardened
against 11 specific mutations. Prefer widening its file list to copying it.

## Related

- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243) · PUB-055 (#236) · #229
