---
name: layering-guard-review-traps
description: Traps in tests/test_layering.py's AST storage-privates guard (#142), the migrate_storage presence-based resume, and ManagedStorage.head_object's error logging
metadata:
  type: project
---

`publisher_v2/tests/test_layering.py::test_web_and_tools_use_the_storage_protocol_only` (#142) is an
AST guard, not a grep. Re-probed after the #142 widening (accepts `ast.Attribute` bases) and again
on the rebase onto integration/128:

- Caught (mutation-verified): `storage._bucket`, `target.client`, `self.storage._bucket`,
  `a.b.storage._bucket`, `class X(ManagedStorage)` and dotted bases (`ms.ManagedStorage`).
  Dunders ignored; `request.client.host` is correctly NOT a hit (owner must be storage/source/target).
- Still blind: renamed locals (`st._bucket`), `getattr(storage, "_bucket")`, aliased base
  (`import ManagedStorage as MS; class X(MS)`).
- False-positive surface since the widening: any `self.target._x` / `obj.source._x` where
  `target`/`source` is NOT storage (e.g. a publisher target) trips the guard.
**How to apply:** when a diff touches this test, probe it with synthetic files rather than trusting
the name; check the `self.<attr>` chain form and the non-storage `target`/`source` FP case.

Migration tool (`tools/migrate_storage.py`) standing facts (final #142 shape):
- Resume is presence-based: `await target.exists(key)`. `ManagedStorage.exists` = `head_object(...)
  is not None` (one counted op); `DropboxStorage.exists` raises `StorageNotSupportedError`.
  The old ETag-vs-content_hash compare is gone; archived PUB-031 AC5 is struck through and the
  retirement is recorded in ARCHITECTURE.md's Migration CLI section.
- A resumed skip now ALSO HEADs the sidecar key (`_copy_sidecar(..., only_if_missing=True)`), so a
  resumed run costs 2 HEADs per image. That is deliberate: it heals sidecars orphaned by a run
  interrupted between the image put and the sidecar put.
- The summary logs `storage_ops` via `getattr(target, "drain_ops_count", None)` — `None` when the
  target has no counter (the protocol does not require one). The drain block now has TWO filters:
  `inspect.iscoroutine(drained) -> close(); None` and `isinstance(drained, int)`. They are
  double-defended, so `test_an_async_counter_is_not_logged_as_a_coroutine` (AsyncMock counter) goes
  red ONLY when BOTH are removed — removing either alone stays green (the leftover un-awaited
  coroutine is just a RuntimeWarning, and pytest here does not error on warnings). To pin the
  isinstance arm on its own, a target whose `drain_ops_count` returns a non-int (e.g. `"7"`) is
  needed. `drained.close()` is safe in practice: the only target is ManagedStorage, whose
  `drain_ops_count` is sync; closing a never-started coroutine runs no body, so nothing is lost
  beyond the (already unreported) count.
- The `exists` failure arm now logs `migration_presence_unknown` (WARNING, `file` + `error_type`)
  and falls through to the copy; mutation-verified red both ways (drop the log, or turn it into a
  skip). It fires per image, so a broken target yields one WARNING per file — accepted: an
  operator-run CLI whose resume has degraded into a full re-copy should be loud.
- `async_main` is now covered by `TestCliWiring` (the `resume=args.resume` wiring regressed once).

`ManagedStorage.head_object` (#142) logs `head_object_failed` (WARNING, `code` + `key_length`) for
any ClientError code outside `404/NoSuchKey/NotFound`, but STILL returns `None` — a 403 or throttle
therefore still reads as "missing" and re-copies; it is merely visible now. ARCHITECTURE.md was reworded
at 4ac387a to say so explicitly (still reports absent, re-copies, but is no longer silent) —
verified against the code. No log-spam risk: the hot thumbnail path
uses `get_file_metadata` (separate head, raises), and `head_object` is only reached from the admin
delete route and the CLI — unlike the per-response warning fixed in #163.
See also [[storage-protocol-review-traps]], [[mutation-check-review-technique]].
