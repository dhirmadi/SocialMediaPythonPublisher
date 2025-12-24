# Heroku Pipeline Migration — Story Design

**Feature ID:** 021  
**Story ID:** 021-07  
**Parent Feature:** config_env_consolidation  
**Design Version:** 1.0  
**Date:** 2025-12-23  
**Status:** Design Review  
**Story Definition:** 021_07_heroku-pipeline-migration.md  
**Parent Feature Design:** ../../021_design.md

## 1. Summary

### Problem & Context
The Heroku `fetlife` pipeline currently uses `FETLIFE_INI` config var to bootstrap an INI file at dyno startup. With Feature 021's env-first configuration, this bootstrap is no longer needed. This story provides the rollout plan and migration instructions.

### Goals
- Document migration procedure for Heroku pipeline apps
- Ensure apps can start without `FETLIFE_INI`
- Provide local development migration guide
- Verify web runtime doesn't require INI file when env vars are set

### Non-Goals
- Implementing Orchestrator API (Epic 001)
- Changing business logic
- Automated migration scripts

## 2. Context & Assumptions

### Current Behavior
- `Procfile` or startup script writes INI file from `FETLIFE_INI` env var
- `CONFIG_PATH` points to the generated INI file
- Application requires INI file to exist

### Constraints
- Migration must be gradual (canary first)
- Rollback must be possible
- Local development must continue working

### Dependencies
- Stories 01-06: All env var parsing and deprecation logic complete

## 3. Requirements

### 3.1 Functional Requirements

**SR1:** Application starts successfully when:
- All required JSON env vars are set
- `FETLIFE_INI` is not set
- No INI file exists

**SR2:** Document required Heroku config vars for env-first mode

**SR3:** Document rollout procedure with verification steps

**SR4:** Document local `.env` migration from INI

### 3.2 Non-Functional Requirements

**NFR1:** Zero downtime during migration

**NFR2:** Clear rollback path if issues arise

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

**Current Procfile (conceptual):**
```
web: ./write_ini_from_env.sh && uvicorn app:app
```

**Proposed:**
```
web: uvicorn publisher_v2.web.main:app --host 0.0.0.0 --port $PORT
```

No INI bootstrap needed when env vars are set.

### 4.2 Components & Responsibilities

**`loader.py` behavior with missing INI:**
- If `config_file_path` doesn't exist but all JSON env vars are set:
  - Skip INI parsing entirely
  - Use only env var configuration
- If `config_file_path` doesn't exist and JSON env vars missing:
  - Raise ConfigurationError (need some config source)

**This may require a small code change:**
```python
# Current:
if not os.path.exists(config_file_path):
    raise ConfigurationError(f"Config file not found: {config_file_path}")

# Proposed:
if not os.path.exists(config_file_path):
    # Check if env-first mode is viable
    if _has_required_env_config():
        logger.info("No INI file found; using env-first configuration")
    else:
        raise ConfigurationError(f"Config file not found: {config_file_path}")
```

### 4.3 Data & Contracts

**Required Heroku Config Vars (env-first):**

| Var | Type | Required | Notes |
|-----|------|----------|-------|
| `OPENAI_API_KEY` | secret | Yes | |
| `DROPBOX_APP_KEY` | secret | Yes | |
| `DROPBOX_APP_SECRET` | secret | Yes | |
| `DROPBOX_REFRESH_TOKEN` | secret | Yes | |
| `STORAGE_PATHS` | JSON | Yes | |
| `PUBLISHERS` | JSON | Yes | Can be `[]` |
| `TELEGRAM_BOT_TOKEN` | secret | If telegram | |
| `EMAIL_PASSWORD` | secret | If fetlife | |
| `EMAIL_SERVER` | JSON | If fetlife | |
| `OPENAI_SETTINGS` | JSON | No | Has defaults |
| `CAPTIONFILE_SETTINGS` | JSON | No | Has defaults |
| `CONFIRMATION_SETTINGS` | JSON | No | Has defaults |
| `CONTENT_SETTINGS` | JSON | No | Has defaults |

**Deprecated (to remove after migration):**
- `FETLIFE_INI`

### 4.4 Error Handling & Edge Cases

**Missing required config:**
```
ConfigurationError: Cannot start in env-first mode: missing STORAGE_PATHS, PUBLISHERS
```

**Partial env (some JSON, some INI needed):**
- Works with deprecation warning from Story 06
- Not recommended for production

### 4.5 Security, Privacy, Compliance

- No new security considerations
- Same secret handling as before

## 5. Detailed Flow

### Rollout Procedure

```
1. Select canary app in fetlife pipeline
2. Set new env vars on canary (keep FETLIFE_INI for now):
   heroku config:set STORAGE_PATHS='...' -a canary-app
   heroku config:set PUBLISHERS='...' -a canary-app
   heroku config:set EMAIL_SERVER='...' -a canary-app
   (other vars as needed)
3. Restart and verify:
   - /health returns 200
   - Web UI loads
   - Random image works
   - Admin login works
4. Remove FETLIFE_INI from canary:
   heroku config:unset FETLIFE_INI -a canary-app
5. Restart and verify again
6. Monitor for 24 hours
7. Roll forward to remaining apps (5-10 at a time)
8. Remove FETLIFE_INI from all apps
```

### Local Migration

```
1. Copy dotenv.v2.example to .env
2. Set secrets (from existing .env or password manager):
   - OPENAI_API_KEY
   - DROPBOX_* credentials
   - Publisher secrets as needed
3. Convert INI to env vars:
   # From [Dropbox] section:
   STORAGE_PATHS='{"root": "<image_folder>", "archive": "<root>/<archive>", ...}'
   
   # From [Content] toggles + sections:
   PUBLISHERS='[...]'
   
   # From [Email]:
   EMAIL_SERVER='{"smtp_server": "...", "smtp_port": ..., "sender": "..."}'
4. Run app and verify:
   make preview-v2
5. Check for deprecation warnings (should be none with full env config)
```

## 6. Testing Strategy

### Verification Checklist

| Check | Method |
|-------|--------|
| Health endpoint | `curl localhost:8000/health` |
| Web UI loads | Browser test |
| Random image works | Click random in UI |
| Admin login | Auth0 flow completes |
| Publish works | Test publish (staging only) |
| No deprecation warning | Check logs |

### Integration Test
- Add test that starts app with only env vars (no INI file)
- Verify all endpoints work

## 7. Risks & Alternatives

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Missing env var blocks startup | Medium | High | Canary testing first |
| JSON escaping issues | Medium | High | Verify with heroku config |
| Auth0 issues after restart | Low | Medium | Test auth flow explicitly |

### Rollback Plan

```
1. Restore FETLIFE_INI:
   heroku config:set FETLIFE_INI='...' -a affected-app
2. Restart dyno:
   heroku ps:restart -a affected-app
3. Verify app works with INI
4. Investigate issue before retrying
```

## 8. Work Plan

### Tasks

1. Add `_has_required_env_config()` helper to `loader.py`
2. Update INI file check to allow env-first mode
3. Create `dotenv.v2.example` (if not done in Story 06)
4. Document rollout procedure in story/feature docs
5. Create local migration guide
6. Test on staging Heroku app
7. Execute production rollout

### Definition of Done

- [ ] App starts without INI when env vars set
- [ ] Clear error message when required env vars missing
- [ ] Rollout procedure documented
- [ ] Local migration guide complete
- [ ] Verified on staging Heroku app
- [ ] Production apps migrated (or plan documented)

