# Implementation Handoff: PUB-085 — Gitleaks CI Honesty and Admin-UI Behaviour Coverage

**Status:** Ready for implementation

## For Claude Code

Two parts, one PR each, from worktree `../SocialMediaPythonPublisher-pub084` on branch `chore/pub-085-gitleaks-and-ui-e2e`: part A (#303, AC1-AC2) then part B (#305, AC3).

### Test-first targets

| AC | Test name (exact function) | File |
|----|----------------------------|------|
| AC1 | `test_ci_precommit_job_skips_gitleaks_and_says_why` | `test_ci_security_gates.py` |
| AC2 | `test_gitleaks_is_documented_as_a_local_hook` | `test_ci_security_gates.py` |
| AC3 | `test_back_to_grid_opens_the_page_holding_the_current_image` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_back_to_grid_falls_back_when_the_page_is_empty` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_page_size_is_remembered_across_reloads` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_page_size_control_is_locked_while_uploading` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_rate_limited_upload_waits_and_retries` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_enqueuing_clears_completed_queue_entries` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_escape_leaves_multi_select_and_items_expose_aria` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_leaving_the_page_while_uploading_is_guarded` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_selecting_a_grid_item_while_uploading_asks_first` | `e2e/test_ui_behaviours.py` |
| AC3 | `test_password_auth_mode_never_shows_a_password_prompt` | `e2e/test_ui_behaviours.py` |
| AC4 | `test_default_run_deselects_e2e` (existing) | `test_suite_hygiene.py` |

### Mock boundaries

External services only (S3 via `FakeS3`, OpenAI via the scripted fake installed by the e2e harness). Never patch app internals; drive the UI. Server responses such as a 429 are produced by the real app (its rate limiter) or by `page.route` on the browser side, stated per test.

### Non-negotiables

- Flows wait on DOM state or network events, never fixed sleeps; each is mutation-checked against a template variant that breaks its behaviour.
- A flow that fails on current code is a found defect: fix `index.html` in the same PR (developer role), never weaken the flow.
- `code-reviewer` on both parts; `security-auditor` on part A (CI security gate).

### Claude Code command

```
/implement PUB-085
```
