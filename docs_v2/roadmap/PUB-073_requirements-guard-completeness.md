# PUB-073: Close the Requirements-Guard's Two Known Blind Spots

| Field | Value |
|-------|-------|
| **ID** | PUB-073 |
| **Category** | Ops |
| **Priority** | P2 |
| **Effort** | XS |
| **Status** | Proposal |
| **Dependencies** | PUB-066 |

## User Story

As a maintainer, I want the requirements-file guard to catch a dangling constraints reference and a
reference written with trailing punctuation, so that the two defects it currently waves through
cannot reproduce the Dependabot abort it exists to prevent.

## Problem

PUB-066 added `publisher_v2/tests/test_requirements_files.py`, which asserts no tracked
`requirements*.txt` references a missing target and no live doc recommends installing from an absent
one. Two gaps were identified during its review and deliberately left open, because closing either
changes what AC1/AC2 assert and so needs a spec, not a review fix:

1. **`-c` / `--constraint` is not matched.** `REQUIREMENT_FLAG` covers only `-r` / `--requirement`.
   pip follows constraints files as well, so a dangling `-c missing.txt` reproduces the exact
   `dependency_file_not_found` abort PUB-066 fixed, and the guard stays green.
2. **Trailing punctuation defeats the filename match.** The target is captured as `[^\s#]+`, so
   `-r requirements.txt.` at the end of a sentence, `-r requirements.txt)` inside parentheses, or
   `` `-r requirements.txt` `` in an inline code span yields a captured name ending in `.`, `)` or a
   backtick. `_is_requirements_name` then fails to match `*requirements*.txt` and the line is
   silently skipped.

Those prose citations are shielded by `_code_lines`, which returns only lines inside a code block, so
a backticked command in a paragraph is never scanned at all. (An earlier draft of this item claimed
the trailing backtick in the capture was what protected them. That is wrong: `PUB-066_handoff.md:35`
captures a clean `requirements-dev.txt` — the token is followed by whitespace — and is skipped purely
because its line is prose.) The constraint on gap 2 is therefore narrower than it looked: stripping
trailing punctuation cannot start flagging prose, because prose lines never reach the matcher. It
can, however, start flagging a *fenced* line that quotes the old command, so the fixture tests below
still matter.

## Desired Outcome

A dangling `-c` reference fails the guard, and a reference with trailing punctuation is matched on
its real filename — with no new false positive on prose that quotes the old command.

## Scope

**In scope:**
- Widen `REQUIREMENT_FLAG` to `-c` / `--constraint` (and the `-cfile` / `--constraint=file` spellings
  already handled for `-r`).
- Strip trailing punctuation that cannot be part of a filename from the captured target.
- Add fixture tests pinning the two directions gap 2's fix could break: a fenced `-r requirements.txt.`
  for an absent file must fail, and a fenced line quoting the old command for a file that exists must
  not.
- Amend AC1/AC2 wording in `PUB-066_dependabot-python-updaters.md` to name constraints files, with a
  pointer to this item.

**Out of scope:**
- Scanning unfenced prose for install instructions. That stays excluded by design (see above).
- Full CommonMark parsing. `_code_lines` remains a state machine; its documented residual (a
  4-space-indented list continuation read as a code block) is acceptable and fails loud, not open.
- `pip`'s other flags (`-e`, `--find-links`, `--index-url`) — none of them name a file whose absence
  aborts file fetching.

## Acceptance Criteria

- AC1: Given a tracked requirements file containing `-c missing.txt`, when
  `test_no_requirements_file_references_a_missing_target` runs, then it fails naming the file, line
  and target. Equally for `--constraint missing.txt`, `-cmissing.txt` and `--constraint=missing.txt`.
- AC2: Given a tracked requirements file containing `-r requirements.txt.` or `-r requirements.txt)`
  where that file is absent, when the same test runs, then it fails, having matched the target on its
  real filename rather than skipping it.
- AC3: Given the punctuation-stripping change, when
  `test_the_docs_do_not_recommend_a_missing_requirements_file` runs against the tracked docs that
  cite `pip install -r requirements-dev.txt` in prose backticks (`PUB-066_summary.md`,
  `PUB-066_handoff.md`, and this item), then it still passes, and a fixture test asserts the
  same command inside a fence for an absent file does fail — so the stripping is shown to widen
  matching without widening the scanned region.
- AC4: Given each behaviour above, when it is implemented, then a mutation check is recorded showing
  the test red before and green after — reading the matcher is not evidence.

## Implementation Notes

`REQUIREMENT_FLAG` and `_is_requirements_name` are adjacent in
`publisher_v2/tests/test_requirements_files.py`; the whole change is in that file plus the AC wording
in PUB-066's spec. Strip only characters that cannot end a filename here (`.`, `,`, `)`, `` ` ``,
`'`, `"`, `;`, `:`), and do not strip a trailing character that leaves the name without its `.txt`.

AC4 exists because PUB-066's first review passed a matcher that was partly vacuous — the git pathspec
was wider than the basename filter, so `dev-requirements.txt` was fetched and silently skipped. That
was found only by reintroducing the defect.

## Risks

- **Over-eager stripping invents filenames.** Stripping too much could turn an unrelated token into a
  plausible requirements name and produce a false failure. Keep the strip list closed and explicit.
- Widening to `-c` may surface a pre-existing dangling constraints reference; that would be a real
  find, and the fix belongs with it rather than in a suppression.

## Success Metrics

- No requirements-file reference class remains that the guard skips silently.

## Related

- PUB-066 (#245) added the guard and logged both gaps; PUB-072 covers the separate question of
  whether a declared Dependabot ecosystem has any manifest at all.
