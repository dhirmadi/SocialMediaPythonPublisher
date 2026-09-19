---
name: tdd-discipline
description: >-
  The red-green-refactor TDD law for publisher_v2: write a failing pytest test
  before any implementation, write minimal code to pass it, refactor only with
  tests green, and never blindly adjust a failing test to match broken code. Mock
  only external services (Dropbox, OpenAI, Telegram, SMTP) at their client
  boundary. Use when implementing a roadmap item, writing or fixing tests under
  publisher_v2/tests/, or when a test fails and it's unclear whether the test or
  the code is wrong.
---

# TDD discipline

## The law (non-negotiable)

1. **Spec first.** No feature lands without an acceptance criterion in a roadmap item
   (`docs_v2/roadmap/PUB-NNN_slug.md`). Bug fixes reference an existing one or a clear
   description of the regression.
2. **Failing test first.** Write the test before the implementation. Run it and confirm
   it fails *for the right reason* (assertion failure, not an import/syntax error).
3. **Minimal code.** Write the smallest implementation that makes the failing test pass.
   No speculative abstractions, no "while I'm here" scope creep.
4. **Refactor green.** Only refactor with tests passing. Re-run `pytest` after every
   refactor step.
5. **Never blindly adjust a failing test.** A failing test is a diagnostic signal.
   Determine whether the *test* or the *code* is wrong by re-reading the roadmap item —
   fix whichever side is actually incorrect. Only rewrite a test when it's genuinely
   wrong (stale assertion, bad mock, changed spec) and say why.

## Mock boundaries

- Mock only **external systems** at their client boundary: Dropbox, OpenAI, Telegram,
  SMTP. Use `unittest.mock.patch` / `pytest.monkeypatch`; reuse fixtures in
  `publisher_v2/tests/conftest.py` before writing new ones.
- Do not mock internal `publisher_v2` modules — if a unit test needs to reach through
  several internal layers, that's a signal the boundary is drawn in the wrong place, not
  a reason to mock it away.

## Hard gate

`git commit` is blocked (exit 2) by `.claude/hooks/pre-commit-tests.sh` if the pytest
suite is red. Fix the failing test/code — don't try to bypass the hook.

## Structural enforcement via subagents

Laws 2–4 aren't just discipline to remember inline — Claude Code's `/implement` enforces
the role split structurally by delegating to isolated-context subagents in
`.claude/agents/`: `test-engineer` writes the failing test and is not given the
implementation task; `developer` writes the code and is not allowed to edit the test
files it's working against; `code-reviewer` (read-only) checks the result afterward.
Cursor's own hardening/review gates use the equivalent pattern via `.cursor/agents/`
(`architect-reviewer`, `delivery-reviewer`) — prefer delegating to the named subagent
over doing every role yourself in one context.

## Conventions

Framework, naming, and coverage-threshold specifics live in `.claude/rules/testing.md`
(loaded automatically when editing `publisher_v2/tests/**`) — read that for the
authoritative detail; this skill is the law, that rule is the how-to.
