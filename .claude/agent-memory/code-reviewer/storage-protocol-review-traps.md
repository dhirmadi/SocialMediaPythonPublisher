---
name: storage-protocol-review-traps
description: Recurring review traps in the storage protocol layer (runtime_checkable isinstance, ClientError swallowing, PUB-045 op counts)
metadata:
  type: project
---

Traps to re-check whenever `services/storage_protocol.py` or its backends change (introduced in #96):

- `ObjectStorageProtocol` is `@runtime_checkable`: `isinstance()` only checks method *presence*, so `DropboxStorage` (whose object ops all raise `StorageNotSupportedError`) also passes the check. Library availability is enforced by `_check_library_available` (config-based), not isinstance — don't accept isinstance as a guard.
- `ManagedStorage.head_object` returns `None` on *any* `ClientError` (403/500 look like "missing"), and has no tenacity retry unlike the other methods. Behavior-parity with pre-#96 router code, accepted as a warning then; flag if it spreads to new call sites where "missing" triggers destructive paths.
- PUB-045 metering lives *inside* each ManagedStorage method; `move_object` counts 2 ops up front even if the copy fails. Web-layer code must never call `._count_ops` again.

**Why:** these were the only near-findings in the #96 layering review; everything else was clean.
**How to apply:** targeted grep for `isinstance(.*ObjectStorageProtocol`, `except ClientError` returning None, and `_count_ops` outside `services/` on future storage diffs.
