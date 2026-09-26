---
name: sidecar-sd-line-cache-miss-traps
description: PUB-051 merge: making an empty sidecar SD line a web-Analyze cache miss wipes #147 operator edits, because generate_and_upload_sidecar rebuilds metadata from scratch
metadata:
  type: project
---

Any new web Analyze cache-miss condition is a data-loss path: the miss falls through to
`generate_and_upload_sidecar`, which rebuilds metadata from scratch and drops `caption`,
`caption_edited`, `caption_submitted` (#147 retry text). Before PUB-051 only force_refresh did that.

**Why:** PUB-051 (6186994) made "SD prompts on + empty line 1" a miss, while the same change made
`update_sidecar_with_caption` leave line 1 empty (override publish, no prior sidecar / no SD). So a
publish-then-Analyze sequence silently regenerates and erases operator text. The shipped test
(test_override_publish_never_moves_the_social_caption_into_the_sd_slot) ran exactly that sequence
and never asserted the override survived.

**How to apply:** when a diff widens the Analyze miss condition, repro with a sidecar holding
empty line 1 + caption/caption_edited/caption_submitted and check what gets written. Also: a
"kept SD line" reader preserves legacy social captions on line 1 forever, so "corrected on next
rewrite" claims are false. Related: [[caption-sidecar-review-traps]].
