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
- Resolved in 911390e by ten `test_code_lines_*` fixture tests. Was: a 64-line hand-rolled
  CommonMark-ish state machine with **no direct unit tests**.
  Mutation-proven twice: restoring the old `inside = not inside` toggle, and making `_code_lines`
  return `[]` outright, both leave the suite green. AC2 has zero positive fixture — no tracked doc
  has a fenced install-from-missing-file line, so the test cannot distinguish a working matcher
  from a dead one. Only the false-positive direction is constrained (`_code_lines` returning every
  line goes red on `PUB-066_handoff.md:35`).
- Fixed in 911390e. Was: an indented code block was recognised only after a *blank* line
  (`after_blank`), but CommonMark only forbids interrupting a **paragraph**, so an indented block
  after a heading / thematic break / closing fence was read as prose. Now tracked as
  `paragraph_open` + `NON_PARAGRAPH_LINE`. **Measurement caveat for future reviews:** my "98
  affected sites" figure came from a fence-unaware line scan and was wrong — nearly all were
  already inside fences. Corpus-wide the fix changes the classification of **zero** lines
  (8065 scanned code lines before and after, identical sets). Always diff the two matchers'
  line sets, don't count candidate line pairs.
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

**Post-fix state (911390e, verified):** 12 tests in the file; naive-toggle mutant fails 7, dead
matcher fails 8, and eight separate feature mutations (backtick-info opener, indented-block reset on
fence open, `paragraph_open` → `not blank`, ignore closing info string, ignore fence length, drop tab
indent, drop `<` from `NON_PARAGRAPH_LINE`, require 0-indent fences) each kill exactly one test. The
two `== []` fixtures are one-directional by design (they also pass under a dead matcher) but are
killed by over-classifying mutants, so none of the 12 is vacuous.
**Residual fail-open not in the docstring:** a fence indented 4+ spaces inside a list item with no
blank line before it (`- JS \`x\`:` then `    \`\`\`js`) is neither a fence (>3 spaces) nor an
indented block (list marker keeps a paragraph open) — 3 such sites in live docs, none with an
install command. Deliberate: making list markers close a paragraph would make the list-continuation
false positive common.
