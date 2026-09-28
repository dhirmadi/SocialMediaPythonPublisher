---
name: caption-limit-dedup-review-traps
description: PUB-084 wave 5 (#281/#277) - how to prove a caption/prompt refactor is behaviour-neutral; sandbox-safe baseline recipe; index.html dedup residue
metadata:
  type: project
---

Reviewed 2026-09-28 (uncommitted wave 5 on refactor/pub-084-dry-review-batch).

- **Behaviour-neutral proof that worked:** copy the working src to scratch/headsrc, overwrite the touched modules with
  the HEAD blob (show HEAD:path redirected to a file, one plain command each), then run the same python -c dump script
  twice with PYTHONPATH pointing at each tree and diff the JSON. Covered _build_multi_prompt (dict/None/{} history x
  voice examples), senses_seed, sample_voice_examples, strip_emoji_and_hashtags, two_sentence_emoji_rhythm_share,
  format_caption on under-limit input. Only over-limit email outputs differed (expected). PYTHONPATH beats the .pth.
- **Sandbox:** heredocs, for-loops and shell vars are refused, and so is any python -c whose text contains the VCS
  tool name. Inline python -c scripts otherwise work; the VCS -C flag on a scratch worktree path works for resets.
- Old _trim_to_length never actually exceeded the limit (base[:max_len-1]+ellipsis); #281 AC15 is about ONE algorithm
  (smart_truncate), so the AC15 test uses smart_truncate as an equality oracle, not only a length bound.
- #277 residue worth re-checking on later template work: handleGridDelete -> removeFromGrid now drops the name from
  selectedFiles but does not call updateSelectionUI (bulk path does). Email subject truncation appends a unicode
  ellipsis although _sanitize_for_fetlife rewrites it to three dots (format_caption already did the same pre-wave).

See [[mutation-check-review-technique]], [[e2e-playwright-review-traps]], [[caption-sample-script-traps]].
