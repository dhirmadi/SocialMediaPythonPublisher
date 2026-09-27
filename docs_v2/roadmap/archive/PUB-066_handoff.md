# Implementation Handoff: PUB-066 — Unblock Dependabot's Python Updaters

**Hardened:** 2026-09-26
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Test name (exact function) |
|----|-----------|-----------------------------|
| AC1 | `publisher_v2/tests/test_requirements_files.py` | `test_no_requirements_file_references_a_missing_target` |
| AC2 | `publisher_v2/tests/test_requirements_files.py` | `test_the_docs_do_not_recommend_a_missing_requirements_file` |
| AC3 | — | N/A — live verification, see spec |

The **Test name** column is the exact `pytest` function name to create. If a different name is
genuinely clearer, record the actual name in `PUB-066_summary.md` next to the AC it satisfies.

### Read this first

The spec's Problem section labels the root cause a **hypothesis**. That is deliberate. The
observable facts are the error text, the single `-r requirements.txt` reference, and that only the
non-requirements-scanning ecosystem succeeded. Dependabot's file-fetch order is not observable from
outside the runner, so AC3 is what actually proves the fix. Do not report this item complete on the
strength of the tests alone — they assert repository hygiene, not that Dependabot recovered.

### Order of work

1. Write the two failing tests first. They must fail against the current tree: `requirements-dev.txt`
   exists and references a missing `requirements.txt`, and two docs recommend installing from it.
2. `git rm requirements-dev.txt`.
3. `.github/DEVELOPMENT.md:43` — replace `pip install -r requirements-dev.txt` with the uv
   equivalent (`uv sync --group dev`). Line 113 also lists the file in a directory tree; drop that
   row. `CONTRIBUTING.md:136` — same substitution; it currently reads
   `pip install -r requirements-dev.txt  # If available`, and the hedge should go with it.
4. Leave `Makefile`'s `export-reqs` / `export-reqs-dev` targets alone, and leave `README.md:132-133`
   alone — they describe the targets, which still work, not the committed file.
5. `CHANGELOG.md:286` mentions the file in a historical entry. Do not rewrite history.

### Mock boundaries

| External service | Mock strategy | Existing pattern |
|-------------------|----------------|------------------|
| None | Read tracked files from disk; no network, no subprocess against Dependabot | `publisher_v2/tests/test_coverage_gate_config.py` reads repo-root config as text |

Enumerate tracked files only (`git ls-files` semantics) so an untracked local export does not fail
the suite. `subprocess` to call `git ls-files` is acceptable here — `test_coverage_gate_config.py`
already imports `subprocess` for a similar purpose — or glob and filter, whichever is cleaner.

### Files likely touched

| Area | Files to modify | Files to create |
|------|------------------|-------------------|
| Deps | `requirements-dev.txt` (delete) | — |
| Docs | `.github/DEVELOPMENT.md`, `CONTRIBUTING.md` | — |
| Tests | — | `publisher_v2/tests/test_requirements_files.py` |

### Non-negotiables for this item

- [ ] Preview mode: N/A — no `publisher_v2/src` runtime code touched.
- [ ] Secrets: none involved.
- [ ] Auth: N/A.
- [ ] Async hygiene: N/A.
- [ ] Coverage: the new test file adds no `src/` coverage; the ≥85% gate is unaffected.
- [ ] Backward compatibility: deleting `requirements-dev.txt` removes an already-broken install
      path. `make export-reqs-dev` regenerates a working one if anyone needs it.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-066_dependabot-python-updaters.md
```
