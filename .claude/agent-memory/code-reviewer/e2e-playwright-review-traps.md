---
name: e2e-playwright-review-traps
description: PUB-084 wave 3 (#299/#272/#300) - playwright e2e mutation results, AC10 guard scope, AC12 dedup guard, sandbox-safe template mutation recipe
metadata:
  type: project
---

Reviewed 2026-09-27 (uncommitted wave 3 on refactor/pub-084-dry-review-batch).

- **Curation one-request e2e cannot see double *registration*.** Registering apiKeep twice on #btn-keep still passes: apiKeep calls disableButtons(true) synchronously and Chromium skips remaining click listeners on a now-disabled button. Only the logout test catches the #272 class (logout button is not disabled by disableButtons; HEAD template sends 10 POSTs). A keep handler that fires two fetches fails, but by a 30s response timeout, not the len(sent) assert.
- Other e2e mutants verified red: lock sets disabled=false; retryDelete early return.
- **AC10 guard (test_no_test_greps_index_html_function_bodies) only flags strings containing `function <name>`.** JS statement pins survive it, e.g. web/test_per_platform_captions_real_app.py asserts `const maxLen = platformLimits[platform];` and `const fromLegacy = ...` in GET / text. These will break on #277 JS dedup.
- AC12 guard proven live: two tests differing only in literals (sync vs async, class vs module) are grouped; empty allowlist.
- e2e needs `-m e2e` (addopts `-m "not e2e"`); CI command `uv run pytest -m e2e -p no:randomly -v` passes with addopts --cov-fail-under (no --cov, so no gate).
- test_requirements_files now fenced-regex only: indented blocks unscanned, unclosed fence = prose (fail-open, was fail-loud), longer closing fence not recognised. See [[requirements-hygiene-test-traps]].

Sandbox recipe: loops, shell variables, or `cd <scratch>` chained after git are refused. For template mutations: cp template to scratchpad once, `perl -0pi -e` with the literal path, run, cp back, cmp. `git show HEAD:path > scratch` works as a single plain command. actionlint: `uvx --from actionlint-py actionlint <file>`. See [[mutation-check-review-technique]], [[web-template-test-traps]].

PUB-085 part B (2026-09-28, test_ui_behaviours.py): 20 implementer mutants + 2 reviewer mutants all red; template swap via scratch plugin pv2_template_swap (PV2_TEMPLATE_DIR monkeypatches publisher_v2.web.app.templates) - run the 'unmodified' control dir first. A navigating mutant in the password-mode flow fails only by a 30 s dispatch_event timeout (URL check after dispatch races the async navigation). Sandbox: heredocs and paths containing 'GitHub' in multi-command lines get refused; single python3 -c writing files works.
