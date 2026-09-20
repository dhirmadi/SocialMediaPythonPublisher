# Social Media Python Publisher — Agent Instructions

## Source of truth

V2 is the active codebase. Work in `publisher_v2/` and `docs_v2/`.
Treat `code_v1/` and `docs_v1/` as **archived — never edit**.

## Quick commands

| Task | Command |
|------|---------|
| Install (prod) | `uv sync` |
| Install (dev) | `uv sync --group dev` |
| Format + lint fix | `make format` |
| Lint | `make lint` |
| Type check | `uv run mypy publisher_v2/src --ignore-missing-imports` |
| Test | `uv run pytest -v --tb=short` |
| Test + coverage | `uv run pytest -v --cov --cov-report=term-missing` (source tree only; fails under 85%) |
| All checks | `make check` |
| Preview | `make preview-v2` (env-first; `--config` is accepted but ignored since #97 stage 4) |

## Tooling

- **Package manager**: `uv` (lockfile: `uv.lock`)
- **Formatter + linter**: `ruff` (config: `pyproject.toml [tool.ruff]`)
- **Type checker**: `mypy` (config: `pyproject.toml [tool.mypy]`)
- **Tests**: `pytest` + `pytest-asyncio` (async mode `auto`)
- **Pre-commit**: `ruff`, `bandit`, `detect-secrets`, `gitleaks`, `pydocstyle`

## Coding standards

- Python 3.12+. Use `X | Y` unions, `match/case` where appropriate.
- Line length: 120 characters. Double quotes for strings.
- Type annotations on all public functions.
- Async functions must stay non-blocking; use `asyncio.to_thread()` for blocking SDK calls.
- Structured logging via `publisher_v2.utils.logging.log_json` — never `print()`.
- Imports sorted by ruff isort (`known-first-party = ["publisher_v2"]`).

## Non-negotiables

- **Spec-driven**: read the roadmap item in `docs_v2/roadmap/` before coding. The spec is the contract.
- **TDD**: write tests before implementation. Tests codify the spec'd behavior.
- **When tests fail**: never blindly adjust tests. Check the spec — fix whichever side is wrong.
- **Backward-compatible**: do not break CLI flags, endpoint contracts, or config semantics unless explicitly asked.
- **Preview mode is side-effect free**: must never publish, archive, or mutate cache/state.
- **Secrets**: never hard-code or log tokens/passwords/keys. Use `.env` + INI config.
- **Web auth**: do not weaken auth; admin requires HTTP auth + server-enforced admin cookie.
- **Async hygiene**: no blocking work in async paths without `asyncio.to_thread`.

## Package layout

```
publisher_v2/src/publisher_v2/
├── app.py          # CLI entrypoint
├── config/         # Pydantic v2 config models, loaders, credentials
├── core/           # Exceptions, domain models, WorkflowOrchestrator
├── services/       # AI, storage (Dropbox), publishers (base, email, instagram, telegram)
├── utils/          # Captions, images, logging, preview, rate_limit, state
└── web/            # FastAPI app, auth, routers, templates (single-page vanilla JS)
```

## Quality gates

| Gate | Command | Threshold |
|------|---------|-----------|
| Format | `uv run ruff format --check .` | Zero reformats |
| Lint | `uv run ruff check .` | Zero violations |
| Type check | `uv run mypy publisher_v2/src --ignore-missing-imports` | Zero errors |
| Tests | `uv run pytest -v --tb=short` | All pass |
| Coverage | `uv run pytest -v --cov --cov-report=term-missing` | ≥80% affected, ≥85% overall |

`--cov-fail-under=85` lives in pytest's `addopts` so the gate survives being run
from a subdirectory. Two consequences worth knowing:

- Any **partial** coverage run (`pytest --cov -k one_test`, a single file) fails
  on the whole-run threshold. Add `--cov-fail-under=0`, or use
  `make test-cov-file FILE=<path>`.
- `pytest -p no:cov` is **not supported**: disabling the plugin leaves
  `--cov-fail-under=85` unrecognised and pytest exits on the unknown argument.

## Development workflow

Roadmap items live at `docs_v2/roadmap/PUB-NNN_slug.md`. Shipped items move to `docs_v2/roadmap/archive/`.

Two-tool lifecycle: Cursor (product management) + Claude Code (implementation).

**Lifecycle**: CREATE → HARDEN → IMPLEMENT → VERIFY → REVIEW → DEPLOY → ARCHIVE.

This is the **only** authoritative lifecycle. `.cursor/commands/_archived/` holds
an older, superseded system (`roles/`, `feature/`, `stories/`) where Cursor itself
authored specs and implementation code — retired because it duplicated and
contradicted the two-tool split above. Do not resurrect it without explicit
instruction.

## Autonomy & approval gates

Explicit map of which lifecycle decisions an agent makes autonomously vs. which require the
user's sign-off. **Fallback rule: if a decision isn't listed below, ask the user rather than
guessing.**

| Stage | Decision | Autonomous | Gated | Notes |
|-------|----------|:----------:|:-----:|-------|
| CREATE | Draft a new roadmap item from a described need (`/product-propose-item`) | ✓ | | User's request is the approval |
| CREATE | Set item priority/effort scores | ✓ | | Uses the documented decision framework; user can override |
| HARDEN | Rewrite vague ACs, add missing error cases, tighten language | ✓ | | Must make ACs *more* testable, never change scope |
| HARDEN | Change the item's scope (add/remove behavior) | | ✓ | Flag as "Outstanding Issue" for the user, don't silently expand/shrink |
| HARDEN | Run the adversarial-review subagent | ✓ | | Skip only for trivial/S-effort items, and say so explicitly |
| IMPLEMENT | Write failing tests from ACs, then minimal code to pass | ✓ | | The TDD cycle itself is autonomous once the spec is `Not Started`/hardened |
| IMPLEMENT | Add a new external dependency (`uv add`) | | ✓ | Ask first — new deps affect the supply chain and coverage baseline |
| IMPLEMENT | Deviate from the spec because it's ambiguous or wrong | | ✓ | Document the deviation in the summary doc and flag it; don't implement silently |
| IMPLEMENT | `git commit` | ✓ (if pytest green) | ✓ (if pytest red) | Hard-gated by `.claude/hooks/pre-commit-tests.sh` — do not try to bypass |
| VERIFY | Run quality gates and report pass/fail | ✓ | | Read-only, no approval needed to run it |
| REVIEW | Approve delivery (`/product-review-delivery` verdict: APPROVED) | | ✓ | User (or the reviewing agent acting on the user's behalf) must see the verification matrix before approving |
| DEPLOY | Open a PR | ✓ | | Reversible, doesn't touch production |
| DEPLOY | Merge to `main` | | ✓ | Only an explicit user merge (or explicit "merge it" instruction) counts as approval |
| DEPLOY | Deploy to staging | ✓ | | Staging is a test environment |
| DEPLOY | Deploy/promote to production | | ✓ | User must review the deploy checklist and explicitly approve |
| DEPLOY | Add/rotate a production secret | | ✓ | User configures the actual secret value; agent never invents or logs one |
| ARCHIVE | Move a shipped item to `archive/`, update README + CHANGELOG | ✓ | | Only after REVIEW is APPROVED and quality gates are green |
| Security | Auth/signing logic changes, admin-cookie or auth-header semantics | | ✓ | Ask before touching `publisher_v2.web.auth` internals |
| Security | Weakening any check listed in `.cursor/rules/20-web-ui-admin-security.mdc` | | ✓ (refuse by default) | Never do this without an explicit, unambiguous instruction |
| Architecture | Adding an ADR for a significant decision | ✓ | | Recording a decision is low-risk; see `docs_v2/03_Architecture/adr/README.md` |
| Architecture | Making the underlying decision an ADR would record (new module boundary, new datastore, new heavy framework) | | ✓ | Route through the `architect-reviewer` subagent first |

### Failure handling

| Situation | Autonomous action | Then |
|-----------|-------------------|------|
| Test failure | Diagnose root cause (spec vs. code); fix the side that's wrong per `.claude/rules/testing.md` | If genuinely ambiguous which side is wrong, halt and ask — never guess by adjusting the test to match broken code |
| Lint/type-check failure | Auto-fix (`ruff check --fix`, `ruff format`) and re-run | If a `mypy` error reveals a real type contract question, halt and ask |
| Transient failure (network timeout, rate limit, flaky external call) | Retry once or twice with backoff | If still failing, halt and ask — don't retry indefinitely |
| Deploy failure | Do not auto-retry a production deploy | Report the failure and wait for the user |
| Pre-commit gate blocks a commit | Read the pytest output, fix the failing test/code | Do not remove or disable the hook to get around it |

### Required MCP servers (for the roles/commands that use them)

Not committed to this repo (MCP servers are configured per-user/machine), but the
following are assumed available by name in various commands:

| MCP server | Used by |
|------------|---------|
| GitHub | `/github/commit`, `/product-deploy`, issue tracking referenced throughout `docs_v2/roadmap/` |
| Heroku | `/experts/heroku`, `/product-deploy` staging/production checks |
| Auth0 (optional) | `/experts/auth0`, if/when Auth0-based web login is in scope |

Set these up in your own Cursor/Claude Code MCP config before running the
commands above; there is no project-level `.cursor/mcp.json` or `.mcp.json`.

## Security rules

- Never hard-code secrets. Secrets come from `.env` and INI config files.
- Never log or echo tokens, passwords, API keys.
- Preview mode must never publish, archive, or mutate cache/state.
- All mutating web endpoints require auth via `publisher_v2.web.auth`.

## Git hygiene

- Commit messages: imperative mood, concise, focused on *why*.
- Never commit `.env`, `configfiles/*.ini` (leftovers from the removed INI path may still hold credentials), `*session.json`, `*.key`, `*.pem`. `publisher_v2/alembic.ini` is tooling config and carries no secrets.
- Run `make format` before committing.

## Scoped instructions

- **Cursor**: see `.cursor/rules/*.mdc` for file-pattern-scoped rules, `.cursor/agents/` for real
  named subagents (`architect-reviewer`, `delivery-reviewer`) invoked by the PM Agent commands
- **Claude Code**: see `.claude/rules/` for path-scoped rules, `.claude/commands/` for slash
  commands, `.claude/agents/` for real named subagents (`test-engineer`, `developer`,
  `code-reviewer`, `security-auditor`) that `/implement` and `/review` delegate to

## Subagents over self-review

Both tools support real, isolated-context subagents (`.cursor/agents/*.md`,
`.claude/agents/*.md` — name + description + tool restrictions, invoked via the Agent/Task tool),
not just prose-described personas. This repo uses them at every point where the same agent
drafting something would otherwise grade its own work: hardening a spec, reviewing a delivery,
writing tests vs. implementing vs. reviewing code, and auditing security-sensitive changes. When
extending the workflow, prefer adding or reusing a subagent over writing a longer inline prompt —
see `.cursor/rules/00-agent-operating-guidelines.mdc` and `CLAUDE.md`'s "Development workflow"
section for the current roster and how each is wired in.
