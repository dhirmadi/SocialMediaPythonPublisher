# publisher_v2 — Active Codebase

`code_v1/` is archived — never edit.

## Structure

- `src/publisher_v2/app.py` — CLI entrypoint (`--config`, `--preview` flags)
- `src/publisher_v2/config/` — Pydantic v2 models, loader, credentials, static YAML configs
- `src/publisher_v2/core/` — `WorkflowOrchestrator`, domain models, exceptions
- `src/publisher_v2/services/` — AI service, Dropbox storage, publisher implementations
- `src/publisher_v2/utils/` — Captions, image processing, structured logging, preview rendering
- `src/publisher_v2/web/` — FastAPI admin UI, auth, templates
- `tests/` — pytest suite (mirrors `src/` structure)

## Key patterns

- All config goes through Pydantic v2 models in `config/schema.py`.
- Orchestration is centralized in `WorkflowOrchestrator` — don't scatter orchestration logic.
- Publishers implement the `Publisher` base class in `services/publishers/base.py`.
- Blocking SDK calls must be wrapped with `asyncio.to_thread()`.
- Logging: use `log_json()` from `utils/logging.py`, never `print()`.
