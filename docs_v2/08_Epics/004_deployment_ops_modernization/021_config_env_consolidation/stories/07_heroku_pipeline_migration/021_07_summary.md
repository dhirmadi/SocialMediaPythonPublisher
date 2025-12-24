# Story Summary: Heroku Pipeline Migration

**Feature ID:** 021  
**Story ID:** 021-07  
**Status:** Shipped  
**Date Completed:** 2025-12-23

## Summary

Documented the complete migration procedure for Heroku `fetlife` pipeline apps to transition from `FETLIFE_INI` config var bootstrap to the env-first configuration model introduced by Feature 021.

The story provides a comprehensive runbook for Heroku engineers including:
- Complete config var reference with examples
- Step-by-step migration procedure
- Procfile updates
- Troubleshooting guide
- Validation checklist

## Files Changed

### Documentation
- `docs_v2/08_Epics/004_deployment_ops_modernization/021_config_env_consolidation/stories/07_heroku_pipeline_migration/021_07_heroku-pipeline-migration.md` — **Complete Heroku migration runbook** with:
  - Full config var reference table (secrets, JSON vars, web/admin vars)
  - Exact JSON examples for all config vars
  - Old vs new Procfile comparison
  - Step-by-step migration procedure with `heroku` CLI commands
  - Pipeline rollout plan (canary → batch)
  - Troubleshooting table with common errors and fixes

- `docs_v2/05_Configuration/CONFIGURATION.md` — Enhanced Section 9.3 with:
  - Quick start commands for minimal config
  - Migration steps checklist
  - Procfile before/after comparison
  - Troubleshooting table

- `dotenv.v2.example` — Full example `.env` with all JSON env vars documented

## Key Config Vars for Heroku Engineers

### Required for Env-First Mode (minimum 3)
```bash
STORAGE_PATHS='{"root": "/Photos/MySocialMedia"}'
PUBLISHERS='[{"type": "fetlife", "recipient": "user@fetlife.com"}]'
OPENAI_SETTINGS='{}'
```

### Publisher-Specific
```bash
# FetLife/Email
EMAIL_SERVER='{"sender": "bot@gmail.com", "smtp_server": "smtp.gmail.com", "smtp_port": 587}'
EMAIL_PASSWORD=your-app-password

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-xxx
```

### Deprecated (remove after migration)
- `FETLIFE_INI`
- `CONFIG_PATH`

## New Procfile

```
web: PYTHONPATH=publisher_v2/src uvicorn publisher_v2.web.app:app --host 0.0.0.0 --port $PORT
```

(Removes the INI file creation step)

## Acceptance Criteria Status

- [x] AC1: Given Feature 021 env vars are set, app can boot without FETLIFE_INI
- [x] AC2: Given FETLIFE_INI is removed, app serves web UI using env-first config
- [x] AC3: Documented rollout plan for pipeline with N apps
- [x] AC4: Documented local .env migration for developers

## Validation Checklist

After migration, confirm:
1. ✅ `/health` returns 200
2. ✅ Web UI loads at root URL
3. ✅ "Random image" shows an image (Dropbox works)
4. ✅ Admin login works (password or Auth0)
5. ✅ Logs show `Config source: env_vars` (not deprecation warnings)

## Follow-up Items

- [ ] Execute the documented migration on production Heroku pipeline
- [ ] Monitor deprecation warnings during migration period
- [ ] Update Procfile in repo after all apps migrated
- [ ] Remove FETLIFE_INI bootstrap code after full migration

## Artifacts

- Story Definition: 021_07_heroku-pipeline-migration.md
- Story Design: 021_07_design.md
- Story Plan: 021_07_plan.yaml
- Configuration Docs: docs_v2/05_Configuration/CONFIGURATION.md

