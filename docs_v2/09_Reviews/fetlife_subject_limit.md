# FetLife subject limit: what we know, and what we do not (#79, #146)

## Status: unverified assumption

`platform_limits.yaml` caps the email/FetLife caption at **240 characters**, and
`utils/captions._MAX_LEN["email"]` agrees. That number came from #79. It was not
measured against FetLife — it was chosen, and it has been treated as fact since.

`publisher_v2/tests/test_captions_platform_limits_static.py` pins it so the
value cannot drift silently, and points here. The pin is a reminder that the
number is unverified, not evidence that it is right.

## What would settle it

#146 asks the account owner for one measurement:

1. Post to FetLife by email with a subject of exactly 264 characters (24 over
   the current cap), each 10th character a digit so truncation is countable.
2. Record what FetLife displays: the full subject, a truncation, or a rejection.
3. If truncated, count the characters that survived.

## Recording the answer

Replace this section with the measurement — the subject sent, what was
displayed, the surviving length, and the date — then update
`platform_limits.yaml`, `_MAX_LEN` and the expectation in the test **in the same
commit**, so the three cannot disagree.

Until then the 240 stands as the conservative guess it has always been: too low
truncates a caption that would have fitted, too high loses the end of one that
did not.
