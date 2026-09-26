# PUB-070: Migrate Off `TestClient`'s Per-Request `cookies=`

| Field | Value |
|-------|-------|
| **ID** | PUB-070 |
| **Category** | Testing |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-065 (merged, #235) |

## Problem

PUB-065 upgraded `starlette` 0.49.3 → 1.7.0, which deprecates passing `cookies=` per request to
`TestClient`: *"the expected behaviour on cookie persistence is ambiguous. Set cookies directly on
the client instance instead."* The suite emits 83 such warnings, from
`publisher_v2/tests/web/test_library_api.py` and `test_library_sort_filter.py`.

This is not cosmetic. Several auth tests assert 401/403 for a request made with **no** cookie, on a
client that earlier in the same test sent an admin cookie. Today per-request cookies do not persist
into the client jar, so those assertions hold. If a future starlette resolves the documented
ambiguity by persisting them, the cookie-less request would silently carry the admin cookie, the
assertion would pass for the wrong reason, and the tests guarding `require_admin` would stop
guarding anything.

A security test that cannot fail is the failure mode PUB-055 was written to eliminate; this is the
same defect class living in the test suite instead of a workflow.

## Desired Outcome

No test depends on per-request cookie semantics, and the negative auth assertions provably still
fail when the guard is removed.

## Scope

**In scope:** migrating the affected call sites to client-level cookies or a fresh client per
request (`publisher_v2/tests/web/conftest.py:154` already does the latter for uploads and is the
model); confirming the negative auth assertions still fail when `require_admin` is stubbed out.

**Out of scope:** changing `publisher_v2/src/publisher_v2/web/auth.py` or any production behaviour —
this is a test-suite change only.

## Acceptance Criteria

- AC1: `uv run pytest -q` emits no `DeprecationWarning` from `starlette/testclient.py` about
  per-request cookies.
- AC2: Mutation check — with `require_admin` neutered, the negative auth tests fail. Record the
  mutation and the observed failures in the summary, as PUB-055 did for its 11 mutations.

## Related

- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243) · PUB-065 (#235) · `.claude/rules/web-security.md`
