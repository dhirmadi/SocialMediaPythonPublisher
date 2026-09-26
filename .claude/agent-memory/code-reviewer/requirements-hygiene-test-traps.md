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
- AC2 matcher only sees lines *inside ``` fences* that also match `pip|uv pip install`. Blind to
  unfenced prose, 4-space indented code blocks, `~~~` fences, and `install` split across lines.
- `ARCHIVED_TREES = ("code_v1/", "docs_v1/")` is load-bearing for AC2: `docs_v1/DOCUMENTATION.md`
  still has `pip install -r requirements.txt` in a fence. It excludes only those prefixes.
- Only tracked file is `code_v1/requirements.txt` (no `-r` lines); CI's `requirements-audit.txt` is
  generated and gitignored, so AC1 never sees it.
- `requirements.txt` / `requirements-dev.txt` are NOT gitignored, so `make export-reqs*` output can
  be re-committed; pinned exports would still pass AC1.
- `uv lock --upgrade && uv sync` (SECURITY.md "Applying Updates") verified to really upgrade here —
  `uv lock --upgrade --dry-run` listed ~40 bumps; every direct dep is a bare `>=`.
