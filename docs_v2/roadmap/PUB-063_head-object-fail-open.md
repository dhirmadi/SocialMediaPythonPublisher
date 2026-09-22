# PUB-063: Distinguish "absent" from "could not tell" in head_object

| Field | Value |
|-------|-------|
| **ID** | PUB-063 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-048 |

> Numbering note: PUB-062 is claimed by an in-flight spec branch (`spec/pub-062-drain-request-timeout`), so this item takes 063.

## User Story

As an operator, I want a write guard that cannot tell whether an object exists to refuse the write rather than assume the object is absent, so that a transient storage fault cannot silently destroy an image I already have.

## Problem

`ManagedStorage.head_object` (`services/managed_storage.py:595-627`) documents that it "never raises: any ClientError yields None". A 403, a throttle and a 503 are therefore indistinguishable from a genuine 404 at every call site. The non-404 branch logs a `head_object_failed` warning (#142) and returns `None` anyway.

That collapse was a reasonable default when the only consumer was the migration tool's resume gate, where reading "missing" costs a re-copy. PUB-048 then added two **write guards** built on the same call, and for those the collapse is backwards:

1. `web/routers/library.py:465` — AC9's upload guard. `head_object(key) is not None` decides whether an existing image is overwritten. On a transient non-404, an existing image reads as absent and `overwrite=false` overwrites it.
2. `web/routers/library.py:541` — AC11's move guard. Same shape: a destination collision reads as "destination free", and `move_object` copies over it then deletes the source, destroying the destination object.

Both guards exist specifically to prevent silent data loss, and both fail **open** in exactly that direction under fault. Found by `security-auditor` during PUB-048 (first at the upload site, then confirmed inherited by the move site) and accepted there as out of scope rather than solved.

Not every caller is affected. `WebImageService.ensure_known_object` (`web/service.py:648-649`) and `_delete_from_storage` map `None` to a 404, so they fail **closed** — a fault makes them refuse, which is safe. Only the two write guards invert.

## Desired Outcome

A caller that needs to know whether an object exists can tell the difference between "the store says no" and "the store would not answer", and the two PUB-048 write guards refuse the write in the second case rather than proceeding.

## Scope

**In scope:**
- A way for a caller to get the non-404 fault surfaced rather than flattened — e.g. `object_exists(key) -> bool` that re-raises `StorageError` on a non-404 code, leaving `head_object`'s current signature and swallowing behavior untouched for existing callers
- Upload (AC9) and move (AC11) guards switched onto it, answering 503 when existence cannot be determined
- The accepted-risk entries in PUB-048 updated to point here once closed

**Out of scope:**
- Changing `head_object`'s own contract or its migration-tool/resume callers (#142 relies on the current behavior)
- `exists()` (`managed_storage.py:629-631`), unless a caller needs it — it has the same collapse but no write depends on it today
- The check-then-act race in both guards (concurrent requests), which is a separate accepted risk
- The orphaned-sidecar overwrite residual from PUB-048 AC11

## Acceptance Criteria

- AC1: Given the S3 client raises `ClientError` with code `403` for `head_object`, when the new existence check is called, then it raises `StorageError` rather than returning `False`.
- AC2: Given the S3 client raises `ClientError` with code `404` (or `NoSuchKey`/`NotFound`), when the new existence check is called, then it returns `False` and does not raise — the genuine-absence path is unchanged.
- AC3: Given `head_object` is called directly (the migration tool's resume gate), when the client raises a non-404 `ClientError`, then it still returns `None` and still logs `head_object_failed` — existing behavior is untouched, so #142's resume semantics do not change.
- AC4: Given an image `a.jpg` exists and the store answers `head_object` with a 403, when `a.jpg` is uploaded without `overwrite=true`, then the response is 503 and `put_object` is never called — the existing image survives.
- AC5: Given `a.jpg` exists in root and the store answers `head_object` with a 403, when `a.jpg` is moved from keep to root, then the response is 503 and neither `copy_object` nor `delete_object` is called.
- AC6: Given the store answers normally, when upload and move run, then their 409/200 behavior is exactly as PUB-048 left it — no regression in the ACs this item builds on.

## Implementation Notes

- Prefer adding a method over changing `head_object`: the swallow is load-bearing for #142 and for the fail-closed callers, and a signature change would touch every one of them.
- The 503 detail should say the store could not confirm the object's state and the request can be retried — do not echo the underlying S3 error code to the client.
- `_count_ops()` already runs inside `_head`; a new wrapper must not double-count a single HEAD through `StorageOpsMeter`.
- Test at the boto3 client seam, per the existing fakes in `tests/web/conftest.py` and `tests/web/test_library_move_sanitizing.py` — both already raise a real `ClientError` for unknown keys, so a 403 variant is a small extension.

## Risks

- A store that answers 403 for a *missing* key under some IAM configurations would turn a legitimate first upload into a 503. Worth checking against the R2/MinIO behavior the fleet actually runs before shipping; if real, the guard should treat 403 as ambiguous only when the caller has list permission on the prefix.
- Converting a silent success into a 503 is a user-visible availability change on a path that currently always succeeds. It is the correct trade (an image is worth more than an upload attempt), but it should be called out in the PR body.

## Success Metrics

- Both PUB-048 write guards refuse rather than overwrite when existence cannot be determined, proven by a test that injects a 403 at the client seam.
- `head_object`'s own behavior and every existing caller are unchanged.

## Related

- [PUB-048: Auth and Library Uniformity](archive/PUB-048_auth-and-library-uniformity.md) — added the two write guards; its Risks section records this fail-open as accepted pending this item
- #142 — made presence the migration tool's resume gate, which is why `head_object` swallows

## Change Log

- 2026-09-22 — Raised from a `security-auditor` finding on PUB-048 (#223), flagged there at the AC9 upload guard and confirmed inherited by the AC11 move guard. Filed as a proposal rather than fixed in-place, because the fix changes a storage-layer contract used by callers outside the web layer.
