---
name: config-env-only-review-traps
description: Post-#97-stage-4 config review traps (env-only loader, get_config ConfigurationError re-raise, dead legacy_model/log_config_source params)
metadata:
  type: project
---

Since #97 stage 4 (2026-09), config is env-only (STORAGE_PATHS/PUBLISHERS/OPENAI_SETTINGS required); INI and orchestrator schema v1 are deleted. Traps for future config diffs:

- `OrchestratorConfigV2` subclasses `OrchestratorConfigV1` in orchestrator_models.py — the V1 class surviving is intentional (base class), not a leftover.
- `get_config` in config/source.py re-raises `ConfigurationError` *before* the stale-serve handlers. Any new `ConfigurationError` raised inside `_build_app_config_v2` / credential paths will bypass serve-stale — only permanent misconfigs may raise it there; transient conditions must use `OrchestratorUnavailableError`.
- `--config` / `CONFIG_PATH` are accepted-but-ignored (warning logged). Diffs that make them meaningful again, or that delete the params, are contract changes.
- Dead surface accepted at removal time (fine to see cleaned up later, don't demand re-addition): `log_config_source(source, ini_sections_used=...)` params, `legacy_model = None` → `OpenAIConfig.model` always None from loader.

**Why:** these were the judgment calls in the stage-4 removal review; the re-raise scope is the one that can silently regress resilience.
**How to apply:** on config/source.py or loader.py diffs, grep `raise ConfigurationError` inside get_config's try block and confirm each site is a permanent misconfig.
