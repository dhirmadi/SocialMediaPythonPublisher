# PUB-075: Scope Dependabot to the Dependencies We Actually Maintain

| Field | Value |
|-------|-------|
| **ID** | PUB-075 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Superseded |
| **Dependencies** | PUB-066 |
| **Archived date** | 2026-09-27 |

> **Superseded 2026-09-27.** Merged into [PUB-079: Dependabot Correctness and Scope Batch](../PUB-079_dependabot-correctness-and-scope-batch.md)
> along with PUB-072, PUB-073 and PUB-076 — all four surfaced from the same PUB-066 live run and touch
> the same `dependabot.yml`/`test_ci_security_gates.py` surface, batched to reduce the number of
> separately-tracked security roadmap items. No scope changed; see PUB-079 for the current AC set
> (AC6-AC10 there trace to this item's AC1-AC6).

## User Story

As a maintainer, I want Dependabot to propose updates only for dependencies we actually maintain, so
that the PR queue is signal rather than noise I have to re-close every week.

## Problem

PUB-066 unblocked the Python updaters. Their first successful run (2026-09-27) opened eight PRs, and
five of them should never have been opened:

**Archived tree.** `code_v1/requirements.txt` is tracked, and both ecosystems read it:

| PR | Branch | File it edits |
|----|--------|---------------|
| [#254](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/254) | `dependabot/pip/replicate-gte-1.0.7` | `code_v1/requirements.txt` |
| [#256](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/256) | `dependabot/pip/configparser-gte-7.2.0` | `code_v1/requirements.txt` |
| [#260](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/260) | `dependabot/uv/configparser-gte-7.2.0` | `code_v1/requirements.txt` |

`configparser` and `replicate` appear nowhere in `pyproject.toml`; they are V1-only dependencies.
`CLAUDE.md` states `code_v1/` is archived and must never be edited, so every one of these PRs is
unmergeable by policy. `directory: "/"` evidently does not confine the scan. #256 and #260 are also
byte-identical proposals from the two different ecosystems.

**Deliberately capped major.** `pyproject.toml` pins `instagrapi>=2.6.9,<3` with a comment recording
why: 3.x swaps the HTTP transport to curl-cffi and changes session persistence, which this repo's
mocked tests cannot verify, and the major bump is its own piece of work.
[#255](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/255) (`pip`, widen to `<4`) and
[#258](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/258) (`uv`, 3.0.13) both try to
lift it. Without an `ignore` rule they will return every week.

**Duplicated ecosystems.** The same run showed `pip` and `uv` proposing the same work twice:
#256/#260 are byte-identical `configparser` bumps, and #255/#258 both target `instagrapi`. PUB-055's
AC5 mandated the `pip` entry before anyone knew how the two would interact; the config's own comment
says `pip` "rarely has a bump to propose on its own" because every direct dependency is a bare `>=`.
So its observed contribution is duplicates plus the `code_v1/` noise above. Deciding its fate belongs
here, with the config, rather than in PUB-072 where it was first drafted — PUB-072 is now just the
manifest-availability test.

## Desired Outcome

Dependabot opens no PR against `code_v1/`, and none that lifts the `instagrapi` major cap, while
still updating everything in the live tree.

## Scope

**In scope:**
- Confine both Python ecosystems to the live tree. Likely `exclude-paths` for `code_v1/`; if that
  proves not to apply to the `pip`/`uv` scanners, an `ignore` entry per V1-only dependency is the
  fallback. Verify by an actual run, not by reading the option reference.
- An `ignore` rule for `instagrapi` major bumps (`update-types: ["version-update:semver-major"]`),
  carrying a comment pointing at `pyproject.toml`'s cap so the two never drift.
- Close the five PRs above unmerged, noting why.
- Extend the Dependabot config test to assert both rules are present, so removing them fails CI.

- **Decide the `pip` entry's fate** (moved here from PUB-072). Either drop it as duplicative of `uv`,
  which amends PUB-055's AC5 and `test_dependabot_config_groups_weekly_pip_and_actions_updates` in the
  same change, or keep it with a recorded statement of what it covers that `uv` does not. Do not leave
  it undecided: every week it stays, it re-opens duplicates.

**Out of scope:**
- Deleting `code_v1/requirements.txt`. The archived tree is kept as-is deliberately; scoping the
  updater is the fix, not editing the archive.
- The manifest-availability test — PUB-072.
- Lifting the `instagrapi` cap. That is its own piece of work, as `pyproject.toml` says.

## Acceptance Criteria

- AC1: Given `.github/dependabot.yml`, when
  `publisher_v2/tests/test_ci_security_gates.py::test_dependabot_excludes_the_archived_v1_tree` runs,
  then it asserts the config scopes the Python ecosystems away from `code_v1/`.
- AC2: Given `.github/dependabot.yml`, when
  `publisher_v2/tests/test_ci_security_gates.py::test_dependabot_ignores_instagrapi_major_bumps` runs,
  then it asserts an `ignore` entry for `instagrapi` covering `version-update:semver-major`.
- AC3: Given the `instagrapi` `ignore` entry, when a reader opens it, then a comment cites
  `pyproject.toml`'s `<3` cap and its reason, so the two cannot silently diverge.
- AC4: Given the `pip` entry, when this item closes, then it is either removed — with PUB-055's AC5
  and `test_dependabot_config_groups_weekly_pip_and_actions_updates` amended in the same change and
  the reason recorded as redundancy with `uv`, not unreadability (`pip` reads PEP 621
  `pyproject.toml`) — or kept, with a comment naming what it covers that `uv` does not.
- AC5: **Live verification.** Given the change merged, when Dependabot next runs (touch
  `dependabot.yml` to force it — a manifest change alone does not), then no new PR targets
  `code_v1/`, none proposes `instagrapi` 3.x, and no two PRs propose the same bump. Link the run.
- AC6: Given the five PRs listed in Problem, when this item closes, then each is closed unmerged with
  a one-line reason. (All five were closed on 2026-09-27; if the config is still unscoped, Dependabot
  will have re-opened equivalents, and those count too.)

## Implementation Notes

`test_dependabot_config_groups_weekly_pip_and_actions_updates` in
`publisher_v2/tests/test_ci_security_gates.py:185` shows how this repo parses the config in a test.

AC4 matters because `exclude-paths`' exact semantics for the `pip`/`uv` scanners are not something to
take on trust — PUB-066 is the cautionary tale of reasoning about Dependabot's file handling from the
outside. Confirm with a real run before closing.

## Risks

- **Over-broad exclusion silences the live tree.** `code_v1/` and `publisher_v2/` must be
  distinguished precisely; an exclusion that catches the live tree would stop real security updates
  while looking like success. AC4's live run plus the continued arrival of legitimate PRs is the check.
- An `ignore` rule is a standing decision that hides real advisories for that dependency's majors. It
  is scoped to majors only, so security patches within 2.x still arrive.

## Success Metrics

- Zero Dependabot PRs against `code_v1/` or `instagrapi` 3.x over the following month, with
  legitimate live-tree PRs still arriving.

## Related

- PUB-066 (#245, #253) unblocked the updaters and surfaced all of this on the first successful run.
- PUB-072 was rescoped to the manifest-availability test alone; the `pip` keep-or-drop decision it
  originally carried now lives here, with the evidence.
