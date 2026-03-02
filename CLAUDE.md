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

## Development methodology

This project follows **spec-driven development** and **test-driven development (TDD)**.

### Spec-driven development
- Features are specified in `docs_v2/08_Epics/` and `docs_v2/08_Features/` before implementation.
- Read the relevant spec/story before writing code. The spec is the contract — implementation must match.
- When a spec and the code disagree, **the spec wins** unless the user explicitly says to update the spec.
- New features require a spec (even a brief one) before coding starts. Ask the user if no spec exists.

### Test-driven development (TDD)
- Write or update tests **before** writing implementation code.
- The TDD cycle: write a failing test -> write minimal code to pass -> refactor.
- Tests are the executable specification — they codify the expected behavior from the spec.

### When tests fail (critical rule)
- **Never blindly adjust tests to make them pass.** A failing test is a signal — investigate it.
- First determine: is the **test** wrong, or is the **code** wrong?
- Read the spec/story to understand the intended behavior, then fix whichever side is incorrect.
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
- Run `uv run ruff check` before committing; zero lint violations in changed files.

## Git hygiene

- Commit messages: imperative mood, concise, focused on *why*.
- Never commit `.env`, `*.ini` (except `*.ini.example`), `*session.json`, `*.key`, `*.pem`.
- Run `make format` before committing to keep formatting consistent.

## Scoped rules

See `.claude/rules/` for topic-specific instructions that load when working with matching files:
- `architecture.md` — V2 layout and orchestration boundaries
- `web-security.md` — FastAPI web UI, admin auth, security
- `captions-sidecars.md` — Caption/sidecar/metadata schemas
- `testing.md` — Test authoring conventions
- `docs.md` — Documentation authoring for `docs_v2/`
