# FetLife subject limit: measured (#79, #146)

## Status: measured 2026-09-27 — 240 characters

`platform_limits.yaml` caps the email/FetLife caption at **240 characters**, and
`ai_prompts.yaml` and `utils/captions._MAX_LEN["email"]` agree. The number came
from #79 as an assumption; #146 asked the account owner to measure it.

## Measurement

- **Date:** 2026-09-27, by the account owner, on the production FetLife account.
- **Sent:** one post-by-email with a 264-character subject (24 over the cap),
  built so each 10-character block ends with its own position:
  `.......010.......020 … .......250.......260.264`
- **Displayed:** the subject was cut off at the 240-character mark.
- **Result:** FetLife's subject limit is 240 characters. The configured cap is
  correct; no value changed.

`publisher_v2/tests/test_captions_platform_limits_static.py` pins 240 and checks
the three locations agree. If FetLife ever changes its limit, re-measure the same
way, record it here, and update `platform_limits.yaml`, `ai_prompts.yaml`,
`_MAX_LEN` and the test in one commit.

## Open question: the subject prefix

The caption is capped at 240 **before** `EmailPublisher` prepends the
`subject_mode` prefix (`"Private: "` is 9 characters, `"Avatar: "` 8;
`services/publishers/email.py`). With `subject_mode` private or avatar, a
caption at the cap produces a 248-249 character subject.

The test above was sent without a prefix, so it does not say whether FetLife
strips the prefix before applying its limit (then 240 is right) or counts it
(then up to 9 characters of the caption are lost). Only matters for instances
using `subject_mode` private or avatar; measure with one prefixed 264-character
subject before changing anything.
