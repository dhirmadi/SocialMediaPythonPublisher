---
name: requirements-hygiene-test-traps
description: PUB-066 repo-hygiene tests — tracked-only git ls-files, fenced-block-only doc matcher blind spots, docs_v1 exclusion is load-bearing, uv lock --upgrade verified
metadata:
  type: project
---

`publisher_v2/tests/test_requirements_files.py` (PUB-066) asserts no tracked `requirements*.txt`
has a dangling `-r` and no live Markdown fenced block recommends `pip install -r <absent file>`.

**Why:** it was written to make the Dependabot-breaking dangling `-r requirements.txt` impossible
to reintroduce; both tests are hand-rolled matchers, so vacuity is the main review risk.

**How to apply when reviewing changes near it:**
- Mutation-proven real (2026-09-26): tracked `requirements-dev.txt` with `-r requirements.txt`,
  `-rreq...`, `--requirement=req...` all go red; untracked copy and `# -r ...` correctly pass.
- AC2 matcher sees lines inside ``` or ~~~ fences (CommonMark same-char, >=-length closing) and
  4-space/tab indented blocks, that also match `pip|uv pip install`. Hardened 2026-09-27: the old
  single `inside = not inside` toggle meant one unbalanced fence silently inverted the rest of a
  file. An unclosed fence at EOF now stays classified as code (fail loud). Still blind to unfenced
  prose (deliberate: several roadmap docs cite the old command in inline backticks) and to `install`
  split across lines.
- `ARCHIVED_TREES = ("code_v1/", "docs_v1/")` is load-bearing for AC2: `docs_v1/DOCUMENTATION.md`
  still has `pip install -r requirements.txt` in a fence. It excludes only those prefixes.
- Only tracked file is `code_v1/requirements.txt` (no `-r` lines); CI's `requirements-audit.txt` is
  generated and gitignored, so AC1 never sees it.
- `requirements.txt` / `requirements-dev.txt` are NOT gitignored, so `make export-reqs*` output can
  be re-committed; pinned exports would still pass AC1.
- `uv lock --upgrade && uv sync` (SECURITY.md "Applying Updates") verified to really upgrade here —
  `uv lock --upgrade --dry-run` listed ~40 bumps; every direct dep is a bare `>=`.

**Post-rewrite matcher traps (reviewed 2026-09-27, commit 64c3093):**
- `_code_lines` is a 64-line hand-rolled CommonMark-ish state machine with **no direct unit tests**.
  Mutation-proven twice: restoring the old `inside = not inside` toggle, and making `_code_lines`
  return `[]` outright, both leave the suite green. AC2 has zero positive fixture — no tracked doc
  has a fenced install-from-missing-file line, so the test cannot distinguish a working matcher
  from a dead one. Only the false-positive direction is constrained (`_code_lines` returning every
  line goes red on `PUB-066_handoff.md:35`).
- Fail-open: an indented code block is recognised only when preceded by a *blank* line
  (`after_blank`). CommonMark only forbids interrupting a **paragraph**, so an indented block right
  after an ATX heading, a thematic break or a closing fence is real code that the guard reads as
  prose. 98 such non-paragraph-then-indented sites exist in tracked live docs. The docstring claims
  the CommonMark rule, so it overstates what the code does.
- Path-dependent state leak: `in_indented_block` is not reset when a fence opens, so
  `    x` / ```` ``` ```` / `fenced` / ```` ``` ```` / `    pip install ...` classifies the last line
  as CODE, while the same file without the leading indented line classifies it as prose.
- Fail-open (narrow): a backtick fence whose info string contains a backtick (```` ```py`x ````) is
  not a valid opener per CommonMark but opens one here, inverting inside/outside for the rest of the
  file — the same inversion class the rewrite was meant to kill. 0 occurrences in tracked docs today.
- Correct (verified against markdown-it `commonmark`): 6-backtick open vs 3-backtick close, `~~~`
  inside ```` ``` ````, closing fence carrying an info string, 3-vs-4 leading spaces, CRLF,
  tab-indented blocks, unclosed fence at EOF (stays code = fail loud), indented block at line 1.
- Roadmap status vocabulary: `Proposal|Not Started|In Progress|Done|Deferred|Superseded`.
  PUB-055/065/066 header tables say "Implementation Complete", which is off-vocabulary — the README
  rows are right, the item files are wrong. Canonical categories are 8 and do **not** include
  `Testing` (PUB-070 uses it).
