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
| Type check | `uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env` |
| Test | `uv run pytest -v --tb=short` |
| Test + coverage | `uv run pytest -v --cov=publisher_v2/src/publisher_v2 --cov-report=term-missing` |
| All checks | `make check` |
| Preview | `make preview-v2 CONFIG=configfiles/fetlife.ini` |

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
| Type check | `uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env` | Zero errors |
| Tests | `uv run pytest -v --tb=short` | All pass |
| Coverage | `uv run pytest -v --cov=publisher_v2/src/publisher_v2 --cov-report=term-missing` | ≥80% affected, ≥85% overall |

## Development workflow

Roadmap items live at `docs_v2/roadmap/PUB-NNN_slug.md`. Shipped items move to `docs_v2/roadmap/archive/`.

Two-tool lifecycle: Cursor (product management) + Claude Code (implementation).

**Lifecycle**: CREATE → HARDEN → IMPLEMENT → VERIFY → REVIEW → DEPLOY → ARCHIVE.

## Security rules

- Never hard-code secrets. Secrets come from `.env` and INI config files.
- Never log or echo tokens, passwords, API keys.
- Preview mode must never publish, archive, or mutate cache/state.
- All mutating web endpoints require auth via `publisher_v2.web.auth`.

## Git hygiene

- Commit messages: imperative mood, concise, focused on *why*.
- Never commit `.env`, `*.ini` (except `*.ini.example`), `*session.json`, `*.key`, `*.pem`.
- Run `make format` before committing.

## Scoped instructions

- **Cursor**: see `.cursor/rules/*.mdc` for file-pattern-scoped rules
- **Claude Code**: see `.claude/rules/` for path-scoped rules, `.claude/commands/` for slash commands
