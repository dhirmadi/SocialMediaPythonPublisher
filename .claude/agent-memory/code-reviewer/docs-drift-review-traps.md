---
name: docs-drift-review-traps
description: Traps when reviewing docs-consistency diffs (#145): markdown-table doc tests key-collide last-wins, --config still exists as an accepted flag, CONTRIBUTING/.github/DEVELOPMENT reference deleted example files
metadata:
  type: project
---

Traps found reviewing #145 (docs drift: mypy command, INI refs, auth model):

- **Doc-assertion tests that parse markdown tables key on the gate-name column and silently drop duplicates.** AGENTS.md has *two* tables with a `Type check` row (quick reference ~L16 and quality gates ~L68); a `dict` comprehension keeps only the last, so a regression in the first row passes. Verified by mutating L16 back to the broken command — test stayed green. Any new docs test of this shape must assert on *every* match (list of values, all equal) or anchor to a specific section.
- **`--config` is still a real argparse flag** in `app.py` (accepted, ignored, deprecation help text). Docs that say it "was removed"/"is gone" are wrong; the correct phrasing is "deprecated and ignored since #97 stage 4" (see [[config-env-only-review-traps]]). CONFIGURATION.md §2 (~L80) states the accurate version — check for self-contradiction in the same file.
- **`CONTRIBUTING.md` and `.github/DEVELOPMENT.md` still tell new contributors to `cp dotenv.example .env` and copy an INI example; neither file exists on disk.** They are outside the usual `README/AGENTS/CLAUDE/docs_v2` grep scope, so INI/setup cleanups keep missing them.
- **`docs_v2/02_Specifications/SPECIFICATION.md` §13 and `USER_FLOW.md` §8 still document `--config path/to.ini (required)`** — live V2 specs, also outside the #145 grep scope.
- `configfiles/*.ini` (fetlife.ini, minimal.ini) exist untracked with real credentials. `make check-secrets` greps `git ls-files`, so it only catches them once staged; dropping `*.ini` from the "never commit" prose removes the human-facing guard. `publisher_v2/alembic.ini` is the one legitimately tracked INI.

**Why:** #145's acceptance grep was scoped to five paths, so it can pass while the repo still contradicts itself.
**How to apply:** on any docs-consistency diff, re-run the acceptance grep *unscoped* over non-archived paths, and adversarially mutate the doc back to the broken state to prove the new test fails.

Second pass (#145 fixes verified):

- **SUPERSEDED by #137 (see [[auth0-only-admin-review-traps]]): the image routes now call `require_admin` unconditionally too.** Historical note follows.
- **`require_admin` was only unconditional on the library router.** `web/app.py` wraps it as `if is_admin_configured(): require_admin(request)` for `/api/images/{f}/analyze|publish|keep|remove|delete`. In a header-auth-only deployment (`WEB_AUTH_TOKEN` set, no `web_admin_pw`/Auth0 → `is_admin_configured()` is False) a Bearer-only client CAN publish and curate. Any doc sentence of the form "a Bearer-only client cannot curate or publish" is therefore conditional, not absolute.
- **`require_auth` does not guard every endpoint.** `POST /api/config/voice-profile` calls only `require_admin`; `/`, `/health*`, `/api/config/*` and the view endpoints use `verify_view_permissions` or nothing. Docs claiming require_auth "guards every endpoint" are wrong.
- **`SPECIFICATION.md` §12 carries the same "HTTP auth ... plus a server-enforced admin session cookie" claim** that #145 fixed in README/CLAUDE. Easy to miss because the #145 issue text only names README:~168 and CLAUDE.md:121.
- **`dotenv.v2.example` still advertises the deprecated `AUTO_VIEW`** (loader.py accepts it as a legacy alias and warns). Feature-flag renames must include this file — Makefile/CONTRIBUTING now point new devs straight at it.
- Markdown-table doc tests keyed on the gate-name column: **"Test" (AGENTS quick reference) and "Tests" (quality gates) are different keys.** Verified by mutation: changing the singular-"Test" row keeps `test_docs_commands.py` green. Same for "Test + coverage" vs "Coverage".

Third pass (#145 review follow-up, working tree of `fix/145-docs-drift`):

- **A rewritten env example can invent an env var the loader never reads.** README's new `.env`
  excerpt carries `FEATURE_ARCHIVE=true` (a translation of the old INI `[Content] archive = true`).
  No such var exists anywhere in `publisher_v2/src`; archiving is `CONTENT_SETTINGS={"archive": …}`,
  which defaults to `True` — so the doc looks right and silently cannot turn archiving off.
  The accompanying loader test even `delenv`s `CONTENT_SETTINGS` and asserts nothing about archive,
  so it ratifies the bug. When reviewing an INI→env doc translation, diff the example's keys against
  `grep -o 'FEATURE_[A-Z_]*'` / the `_parse_*_env` names in `config/loader.py`, key by key.
- **Doc-guard tests carry two independent hand-written allow-lists that disagree.**
  `_repo_docs()` (AGENTS, CLAUDE, Makefile, `.claude/{agents,commands}/*.md`) vs `_CONTRIBUTOR_DOCS`
  (adds CONTRIBUTING.md, `.github/DEVELOPMENT.md`). The mypy-command guard therefore does *not*
  cover the two contributor docs the review flagged.
- **`make X'` regexes only see apostrophe-quoted targets.** `_ADVERTISED_TARGET = r"make ([a-z][\w-]*)'"`
  matches exactly one target (`test`) in the Makefile; the 16 targets listed in the `help:` echo block —
  which is where `make auth` was wrongly advertised — are invisible to it.
- **CI-only enforcement of an acceptance criterion is untraced.** Gating
  `test_the_documented_type_check_command_exits_zero` behind `RUN_SLOW_DOC_CHECKS=1` moves AC
  "mypy exits 0" into `.github/workflows/code-quality.yml` env; nothing fails if that env line is
  deleted. Cheap fix: assert the workflow sets it, in the same test file.
- `docs_v2/08_Epics/**` still shows `make preview-v2 CONFIG=configfiles/fetlife.ini` (historical
  feature docs, outside the AC grep scope). `CONFIGURATION.md:485` INI Procfile is fine — it is the
  "Old (INI-based)" half of a migration before/after pair.
- CONTRIBUTING.md's rewritten test snippet imports `resize_image` from `publisher_v2.utils.images`;
  the real symbol is `resize_image_bytes`.

Fourth pass (#145 second review round — what the fixes look like when they work):

- **The "does the loader actually read this key?" guard that closed the `FEATURE_ARCHIVE` blocker**
  scans `config/loader.py` for *whole-literal* uppercase quoted tokens
  (`r"[\"']([A-Z][A-Z0-9_]{2,})[\"']"`). Whole-literal matching is what keeps it honest: prose error
  strings like `"Use STORAGE_PATHS, PUBLISHERS, ... env vars."` do not match, so no name is admitted
  from a log/error message (verified: all 41 captured names sit on an `environ`/`getenv`/
  `_parse_json_env` line). Its real weakness is the opposite direction — it is **loader.py-only**, so
  documenting a legitimate var read elsewhere (`WEB_AUTH_TOKEN` in `web/auth.py`, any
  `FEATURE_*` read in `utils/features.py`) fails the test. Mutation-confirmed.
- **`README.md:92` still lists `TELEGRAM_CHANNEL_ID`** as an optional secret; it is read nowhere in
  `publisher_v2/src` (telegram takes `channel_id` from the `PUBLISHERS` entry, loader.py:337) and is
  absent from `dotenv.v2.example`. Pre-existing on main. The new guard misses it because
  `_readme_dynamic_config_block()` parses only the ```bash block, not the "Secrets in `.env`" bullet
  list above it — the guard is scoped narrower than the defect class it was written for.
- A README-block parser anchored with `str.index` on a heading is **not** a vacuous-pass risk: renaming
  the heading raises `ValueError` and both tests error loudly (mutation-confirmed).
- Reintroducing `FEATURE_ARCHIVE=true` fails **only** the loader-scan guard — not
  `test_the_readme_env_example_loads_through_the_real_loader`, which merely `setenv`s the extra key.
  Don't accept "two tests cover it" for an invented-env-var defect without mutating.


## SUPERSEDED by #137 (2026-09-20)

The note above says `web/app.py` wraps the image routes as `if is_admin_configured(): require_admin(request)` and that a Bearer-only client CAN publish and curate. That is no longer true: #137 made `require_admin` unconditional on analyze, publish, keep, remove and delete. A Bearer/Basic-only client now gets 503 without Auth0 and 403 without an admin cookie, and Auth0 is the only way to mint the cookie. Docs saying so are CORRECT — do not flag them as drift.
