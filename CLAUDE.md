# Social Media Python Publisher — Claude Code Instructions

## Quick reference

- **Install**: `uv sync` (prod) / `uv sync --group dev` (dev)
- **Format + lint fix**: `uv run ruff format . && uv run ruff check --fix .`
- **Lint only**: `uv run ruff check .`
- **Type check**: `uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env`
- **Test**: `uv run pytest -v --tb=short`
- **Test with coverage**: `uv run pytest -v --cov=. --cov-report=term`
- **Preview (no side effects)**: `PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py --config configfiles/fetlife.ini --preview`
- **All checks**: `make check`

## Project overview

Automated social-media content distribution with AI-generated captions. Images are sourced from Dropbox, analyzed by OpenAI Vision, captioned, and published to Telegram, Instagram, and email. A FastAPI web admin UI provides manual control.

## Source of truth

V2 code lives in `publisher_v2/` and docs in `docs_v2/`. Treat `code_v1/` and `docs_v1/` as **archived — never edit**.

## Package layout

```
publisher_v2/src/publisher_v2/
├── app.py                  # CLI entrypoint
├── config/                 # Pydantic v2 config models, loaders, credentials
├── core/                   # Exceptions, domain models, WorkflowOrchestrator
├── services/               # AI, storage (Dropbox), publishers (base, email, instagram, telegram)
├── utils/                  # Captions, images, logging, preview, rate_limit, state
└── web/                    # FastAPI app, auth, routers, templates (single-page vanilla JS)
```

## Tooling

| Tool | Config location | Notes |
|------|----------------|-------|
| `uv` | `pyproject.toml` + `uv.lock` | Package manager. Add deps: `uv add <pkg>`, dev: `uv add --group dev <pkg>` |
| `ruff` | `pyproject.toml [tool.ruff]` | Formatter + linter (replaces black/isort/flake8). Line length 120, target py312 |
| `mypy` | `pyproject.toml [tool.mypy]` | Type checker. Python 3.12 |
| `pytest` | `pyproject.toml [tool.pytest]` | Tests in `publisher_v2/tests/`, async mode auto |
| `pre-commit` | `.pre-commit-config.yaml` | Hooks: ruff, bandit, detect-secrets, gitleaks, pydocstyle |

## Development workflow — Spec-Based TDD with Teams

This project uses a **two-tool workflow** where Cursor handles product management and Claude Code handles implementation.

### Your role (Claude Code)

You receive **hardened feature specs** from Cursor. These specs have been through product definition, story decomposition, critical review, and hardening. By the time a spec reaches you, it is the contract. Your job is to implement it faithfully using TDD.

### Implementation workflow (teams mode)

When implementing a feature, follow this process:

1. **Read the spec** — start with the handoff document (`NNN_handoff.md`) in the feature folder, then read the feature doc and all story docs
2. **Plan per story** — create `NNN_XX_plan.yaml` for each story with concrete tasks, file paths, and test targets
3. **Test first** — for each story, write failing tests from the acceptance criteria BEFORE writing implementation code
4. **Implement** — write minimal code to make the tests pass
5. **Refactor** — clean up while keeping tests green
6. **Verify** — run the full quality pipeline: `make check`
7. **Document** — create `NNN_XX_summary.md` for each story with what was built, files changed, and test results

### Teams coordination

When working in teams mode (`CLAUDE_CODE_TEAMMATE_MODE=tmux`), roles are:

- **Lead**: reads the spec, creates the implementation plan, coordinates story order
- **Test engineer**: writes tests from acceptance criteria (test-first)
- **Developer**: implements code to pass the tests
- **Reviewer**: runs quality gates and validates spec compliance

All teammates must:
- Read the spec before writing code
- Never deviate from spec'd behavior without explicit approval
- Keep the TDD cycle: failing test → minimal pass → refactor
- Run `uv run ruff check` before considering any story complete

### Spec-driven development

- Roadmap items are specified in `docs_v2/roadmap/` before implementation. The master index is `docs_v2/roadmap/README.md`.
- Read the relevant roadmap item (`PUB-NNN_slug.md`) before writing code. The spec is the contract — implementation must match.
- When a spec and the code disagree, **the spec wins** unless the user explicitly says to update the spec.
- New work requires a roadmap item (even a brief one) before coding starts. Ask the user if no item exists.
- Look for a `PUB-NNN_handoff.md` file — this is the implementation contract prepared by Cursor.

### Test-driven development (TDD)

- Write or update tests **before** writing implementation code.
- The TDD cycle: write a failing test -> write minimal code to pass -> refactor.
- Tests are the executable specification — they codify the expected behavior from the spec.

### When tests fail (critical rule)

- **Never blindly adjust tests to make them pass.** A failing test is a signal — investigate it.
- First determine: is the **test** wrong, or is the **code** wrong?
- Read the roadmap item/spec to understand the intended behavior, then fix whichever side is incorrect.
- If the test correctly asserts the spec'd behavior and the code fails it, **fix the code**.
- Only update a test if the spec has changed or the test genuinely has a bug (wrong assertion, bad mock, etc.).
- When updating a test, explain *why* the test was wrong and what the correct behavior is.

## Coding standards

- Python 3.12+. Use modern syntax: `X | Y` unions, `match/case` where appropriate.
- Line length: 120 characters.
- Double quotes for strings.
- Imports sorted by ruff isort (`known-first-party = ["publisher_v2"]`).
- Type annotations on all public functions. Use `from __future__ import annotations` when needed.
- Async functions must stay non-blocking; use `asyncio.to_thread()` for blocking SDK calls.
- Structured logging via `publisher_v2.utils.logging.log_json` — never `print()`.
- Prefer small, focused edits over wide refactors.

## Security rules (non-negotiable)

- **Never hard-code secrets.** Secrets come from `.env` and INI config files.
- **Never log or echo** tokens, passwords, API keys.
- **Preview mode is side-effect free**: must never publish, archive, or mutate cache/state.
- **Web auth is mandatory**: all mutating endpoints require auth via `publisher_v2.web.auth`.
- Admin requires HTTP auth (`WEB_AUTH_TOKEN` Bearer or `WEB_AUTH_USER`/`WEB_AUTH_PASS` Basic) + server-enforced admin cookie (`pv2_admin`).

## Backward compatibility

Do not break CLI flags, web endpoint contracts, or config semantics unless explicitly asked. Check `docs_v2/03_Architecture/ARCHITECTURE.md` for documented contracts.

## Testing

- Tests live in `publisher_v2/tests/`.
- Use `pytest` with `pytest-asyncio` (async mode `auto`).
- `pythonpath` is `publisher_v2/src`, so imports work as `from publisher_v2.xxx import yyy`.
- **Write tests first** (TDD): tests codify the spec'd behavior before the implementation.
- When a test fails, **diagnose root cause** — fix the code if the test matches the spec; fix the test only if the test itself is wrong.
- Write high-signal tests for new behavior and bug fixes.
- Coverage gates: ≥80% on affected modules, ≥85% overall.
- Run `uv run ruff check` before committing; zero lint violations in changed files.

## Quality gates

Before considering any roadmap item complete, all gates must pass:

| Gate | Command | Threshold |
|------|---------|-----------|
| Format | `uv run ruff format --check .` | Zero reformats needed |
| Lint | `uv run ruff check .` | Zero violations |
| Type check | `uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env` | Zero errors |
| Tests | `uv run pytest -v --tb=short` | All pass |
| Coverage | `uv run pytest -v --cov=publisher_v2/src/publisher_v2 --cov-report=term-missing` | ≥80% affected, ≥85% overall |

## Git hygiene

- Commit messages: imperative mood, concise, focused on *why*.
- Never commit `.env`, `*.ini` (except `*.ini.example`), `*session.json`, `*.key`, `*.pem`.
- Run `make format` before committing to keep formatting consistent.

## Parent project: Platform Orchestrator

Publisher V2 is the **data plane**; it is managed by the **Platform Orchestrator** (control plane).

- **GitHub**: `dhirmadi/platform-orchestrator` (private)
- **Local clone**: `/Users/evert/Documents/GitHub/platform-orchestrator`

The orchestrator provisions instances, manages DNS, stores encrypted BYOK secrets, and serves runtime config. Publisher V2 calls the orchestrator's service API at runtime:

- `GET /v1/runtime/by-host?host=<host>` — full runtime config (non-secret, schema v2)
- `POST /v1/credentials/resolve` — resolve opaque credential refs to secret material

The service-to-service contract is defined in `docs/02_Architecture/publisher-v2-service-api.md` in the orchestrator repo.

When a change spans both repos, update the orchestrator (contract owner) first, then Publisher V2.

## Scoped rules

See `.claude/rules/` for topic-specific instructions that load when working with matching files:
- `architecture.md` — V2 layout and orchestration boundaries
- `web-security.md` — FastAPI web UI, admin auth, security
- `captions-sidecars.md` — Caption/sidecar/metadata schemas
- `testing.md` — Test authoring conventions
- `docs.md` — Documentation authoring for `docs_v2/`

## Custom commands

See `.claude/commands/` for reusable workflow commands:
- `/check` — Run all quality checks
- `/test` — Run tests (optionally filtered)
- `/fix` — Auto-fix lint and formatting
- `/preview` — Run V2 in preview mode
- `/review` — Review staged changes for quality and spec compliance
- `/implement` — Implement a roadmap item from `PUB-NNN_handoff.md` (TDD workflow)
- `/verify` — Post-implementation quality verification for a roadmap item
