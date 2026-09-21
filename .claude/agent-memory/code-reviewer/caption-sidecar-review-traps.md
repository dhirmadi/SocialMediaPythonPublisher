---
name: caption-sidecar-review-traps
description: Per-platform caption (#147) + sidecar interplay traps — override fallback, email-first cache pick vs edited caption, #134 corruption
metadata:
  type: project
---

After #147 (2026-09-19) the web UI publishes `captions: {platform: text}`; workflow falls back to `caption` (= email override or first override) for any platform missing from the dict, then `format_caption` trims it. Re-review fix: `api_publish_image` (web/app.py) now 400s unless `captions` covers exactly the enabled platforms — but the guard is route-only; `WebImageService.publish_image` / `execute(caption_overrides=partial)` still fall back silently. Flag any new caller that bypasses the route.

- `update_sidecar_with_caption` stores ONE `caption` (email/first override); other platforms' edits are never persisted.
- `_select_cached_social_caption` prefers generated email over the edited `caption`. Today #134 corrupts `caption_generated` on override publish, which hides this; once #134 is fixed, re-opened images show pre-edit AI text.
- Sidecar `caption` written by generate_and_upload_sidecar with caption_edited is the SD prompt (sidecar.py ~76) — beware "prefer caption" logic.

- #134 fix (dict->json.dumps) leaves: multi-line string values (edited `caption`) truncated to line 1 by build_caption_sidecar str(); old Python-repr caption_generated stays corrupt forever (rewritten verbatim, warned twice per rehydrate, no filename in warning; ast.literal_eval-recoverable).

- #134 follow-up (PR #155 review round 2): `ast.literal_eval` recovery of legacy `str(dict)` values raises **TypeError** (not ValueError/SyntaxError) on `{{}}`, `{[1]:2}`, `{{1,2}:3}` — unhashable key. Catch TypeError or the read path 500s on a corrupt Dropbox sidecar.
- `parse_sidecar_text` uses `text.splitlines()`, which splits on `\r`, `\x0b`, `\x0c`, `\x85`, `\u2028`, `\u2029` — encoding only values containing `"\n"` still truncates those silently (json.dumps(ensure_ascii=False) does not escape U+2028).
- Resolution (rounds 3-4): no value-shape heuristic can separate an encoded multi-line string from a caption that quotes itself — the builder now writes an explicit `!json ` marker (`ENCODED_STRING_MARKER`, defined in `utils/captions.py` since round 4 — the writer owns the format). Round 4 closed both residuals (marker-prefixed strings are encoded too; a marked value that will not decode logs `sidecar_metadata_json_invalid`). Still open by design: a *string* caption that is itself valid JSON (`{"a": "b"}`, `[1,2]`, `{}`) is decoded to a dict/list and then `rehydrate_sidecar_view` drops `caption` to None — pre-#134 behaviour, closable with the same marker clause.
- `caption_generated` loss is reported in two places by design: the parser warns for values that FAILED to decode; `rehydrate_sidecar_view` warns for values that decoded fine but are not a mapping (plain string, `[1,2]`, scalar). Its `parser_already_warned` guard is derived from the final value's shape, so a decoded string that starts with `{`/`[`/`!json ` is still suppressed-and-lost. Mutate the guard both ways (always/never warn) — one test should fail in each direction.
- `ast.literal_eval` exception surface (400k-case fuzz, py3.12): SyntaxError, ValueError, TypeError only. TypeError is the non-obvious one.
- Superseded quoted-string heuristic (kept for context): `_is_json_encoded_string`: a caption that both starts/ends with `"` and contains a literal backslash escape (`"Type \n for a newline"`, `"C:\\Users"`) is misdecoded.
- Mutation check that works here: delete `source=filename` from the three call sites / drop `TypeError` from the except tuple / drop the `_MAPPING_KEYS` guard — each should turn exactly one test red (round 3: all four do).

**Why:** these were the non-obvious findings in the #147 review.
**How to apply:** on caption/sidecar/workflow override diffs, test a partial `captions` dict and the post-#134 round-trip.

Verification technique (non-mutating): `git worktree add --detach <scratch>/wt main`, copy new test file in, run pytest there, then `git worktree remove --force`. Better than checking out main files into a dirty tree.

## #147 round 3 (PR #150 on integration/128, 2026-09-20)

- `caption_published` (new additive sidecar key, written by `update_sidecar_with_caption`) is **not** filtered by per-platform success: a publish where email raised records email's text anyway. Same pre-existing looseness as the caption-history DB write (`published_captions` loops `enabled_publishers`, not successes).
- A **multi-line email caption cannot be published**: the email publisher puts the caption in the `Subject` header → `HeaderWriteError: folded header contains newline`. The #147 multi-line test passes anyway because it only asserts `status_code == 200`, never `any_success`/per-platform results. Any "multi-line survives" claim must assert publish results, not just the round trip.
- `_select_cached_social_caption` after #147 is email-first over `caption`: a **legacy** sidecar (operator edit in scalar `caption`, no `caption_published`) now serves the AI's `caption_generated["email"]` instead of the published edit — a reversal of #80. Probe: `WebImageService.__new__` + `SimpleNamespace(platforms=SimpleNamespace(email_enabled=True))`.
- Mutations that stay GREEN on the #147 suite (i.e. untested): removing the `CaptionCoverageError → 400` mapping in `web/app.py::raise_for_service_error` (route guard 400s first), and removing the scalar `!json ` string encoding in `build_caption_sidecar` (only the dict/`json.dumps` path is exercised). `_escape_line_breaks` on the dict branch is also untested — `json.dumps` already escapes `\n`; only `\r`/U+2028 need it.
- `caption_published` is deliberately NOT in `_MAPPING_KEYS`, so no legacy-`str(dict)` recovery — correct, it was never written that way.

## #147 round 4 (PR #150 tip d8b0524, 2026-09-20)

- The key was renamed `caption_published` → `caption_submitted` (round 3's W3). `ARCHITECTURE.md:109` still says the old name.
- `caption_edited` in a sidecar means **"an operator-supplied caption was published"**, not "a human edited it": `workflow.py:732` hard-codes `caption_edited=True`, and `update_sidecar_with_caption` only runs when `caption_override or overrides` (workflow.py:717). AI-generated publishes never write `caption`/`caption_edited` at all. So `web/service.py::_edited_scalar_caption` spreading that scalar across every platform is faithful for real data — and it cannot send an over-long caption, because overrides still pass through `format_caption` per platform (workflow.py:653).
- Latent trap for that heuristic: `services/sidecar.py:73-75` (`generate_and_upload_sidecar`) writes `meta["caption"] = sd_caption` when `caption_edited` is passed — the SD prompt under exactly the pair the heuristic trusts (#80 class). Dead today: no production call site passes `caption_edited`.
- Server-side legacy spread silently kills the UI's `fromLegacy` path (`index.html:1249,2534`) added one commit earlier (706277a) to stop republishing a legacy caption as N identical per-platform copies — the two legacy sidecar shapes (with/without an AI dict) now publish in different request shapes.
- Still GREEN under mutation at this tip: removing the scalar `!json ` encoding in `build_caption_sidecar`. The new `cached.json()["caption"] == em` assertion does NOT cover it — that value is served from `caption_submitted` (dict path). To cover the scalar, rehydrate the written sidecar text and assert its `caption`.
- Email subject folding uses `" ".join(subject.split())` (email.py:74): also collapses double spaces and rewrites U+00A0/U+3000/tabs in ordinary single-line subjects. `" ".join(subject.splitlines())` folds only line breaks. Body keeps the unfolded caption.
