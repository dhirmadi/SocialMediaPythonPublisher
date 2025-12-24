# Story: Heroku Pipeline Migration (Stop Using `FETLIFE_INI`)

**Feature ID:** 021  
**Story ID:** 021-07  
**Name:** heroku-pipeline-migration  
**Status:** Shipped  
**Date:** 2025-12-23  
**Parent Feature:** 021_config_env_consolidation

## Summary

Migrate the **Heroku `fetlife` pipeline** off the `FETLIFE_INI` config-var/bootstrap approach and onto the **env-first consolidated configuration** introduced by Feature 021.

This story produces a **repeatable rollout procedure** so that:
- all apps/instances in the `fetlife` pipeline can be migrated safely and consistently
- local development can be migrated via an updated `.env` template and clear instructions

## Background / Motivation

Today the Heroku deployment uses a `FETLIFE_INI` config var to write an INI file at dyno startup (via `Procfile`). Feature 021's goal is to make configuration **env-first** (and ultimately orchestrator-sourced), so we should stop depending on INI for Heroku runtime configuration.

**With Feature 021 shipped:** The web runtime can now boot **without any INI file** when all required JSON env vars are set (`STORAGE_PATHS`, `PUBLISHERS`, `OPENAI_SETTINGS`).

---

## Complete Heroku Config Var Reference

### Required Secrets (keep these as flat env vars)

| Config Var | Example Value | Notes |
|------------|---------------|-------|
| `OPENAI_API_KEY` | `sk-proj-abc123...` | Must start with `sk-` |
| `DROPBOX_APP_KEY` | `abc123xyz` | From Dropbox App Console |
| `DROPBOX_APP_SECRET` | `secret789` | From Dropbox App Console |
| `DROPBOX_REFRESH_TOKEN` | `sl.xxx...` | OAuth2 refresh token |

### Publisher-Specific Secrets (set based on your PUBLISHERS config)

| Config Var | When Required | Example |
|------------|---------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram publisher in `PUBLISHERS` | `123456789:ABC-DEF...` |
| `EMAIL_PASSWORD` | FetLife publisher in `PUBLISHERS` | Gmail app password |
| `INSTA_PASSWORD` | Instagram publisher in `PUBLISHERS` | Instagram password |

### Required JSON Config Vars (minimum for env-first mode)

#### `STORAGE_PATHS` (required)

```json
{"root": "/Photos/MySocialMedia", "archive": "sent", "keep": "favorites", "remove": "trash"}
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `root` | ✅ Yes | — | Dropbox folder path (must start with `/`) |
| `archive` | No | `"archive"` | Subfolder for archived images |
| `keep` | No | `"keep"` | Subfolder for curated "keep" images |
| `remove` | No | `"reject"` | Subfolder for curated "remove" images |

#### `PUBLISHERS` (required)

Array of publisher configurations. **Secrets are NOT embedded** — they're read from flat env vars.

**Telegram example:**
```json
[{"type": "telegram", "channel_id": "@my_channel"}]
```

**FetLife/Email example:**
```json
[{"type": "fetlife", "recipient": "user@fetlife.com", "caption_target": "subject", "subject_mode": "normal"}]
```

**Multiple publishers:**
```json
[
  {"type": "telegram", "channel_id": "@my_channel"},
  {"type": "fetlife", "recipient": "user@fetlife.com", "caption_target": "body"}
]
```

**Empty (disable all publishing):**
```json
[]
```

#### `OPENAI_SETTINGS` (required for env-first, but can be `{}` for defaults)

```json
{"vision_model": "gpt-4o", "caption_model": "gpt-4o-mini"}
```

| Field | Default | Description |
|-------|---------|-------------|
| `vision_model` | `"gpt-4o"` | Model for image analysis |
| `caption_model` | `"gpt-4o-mini"` | Model for caption generation |
| `system_prompt` | (built-in) | Custom system prompt |
| `sd_caption_enabled` | `true` | Generate SD training captions |

**Minimal (use all defaults):**
```json
{}
```

### Optional JSON Config Vars

#### `EMAIL_SERVER` (required when using FetLife/email publisher)

```json
{"sender": "mybot@gmail.com", "smtp_server": "smtp.gmail.com", "smtp_port": 587}
```

#### `CONTENT_SETTINGS`

```json
{"hashtag_string": "#photography", "archive": true, "debug": false}
```

#### `CAPTIONFILE_SETTINGS`

```json
{"extended_metadata_enabled": true, "artist_alias": "My Artist Name"}
```

#### `CONFIRMATION_SETTINGS`

```json
{"confirmation_to_sender": true, "confirmation_tags_count": 5}
```

### Web/Admin Config Vars

| Config Var | Description | Example |
|------------|-------------|---------|
| `web_admin_pw` | Admin password for web UI | `supersecret` |
| `WEB_SESSION_SECRET` | Session signing key | (auto-generated if unset) |
| `WEB_SECURE_COOKIES` | Require HTTPS for cookies | `true` (default) |
| `AUTH0_DOMAIN` | Auth0 domain (optional SSO) | `myapp.auth0.com` |
| `AUTH0_CLIENT_ID` | Auth0 client ID | `abc123...` |
| `AUTH0_CLIENT_SECRET` | Auth0 client secret | `secret...` |
| `AUTH0_ADMIN_EMAIL_ALLOWLIST` | Allowed admin emails | `admin@example.com` |

### Deprecated Config Vars (remove after migration)

| Config Var | Status | Notes |
|------------|--------|-------|
| `FETLIFE_INI` | ❌ Remove | No longer needed with env-first |
| `CONFIG_PATH` | ❌ Remove | Only needed for INI mode |

---

## Procfile Update

**Old Procfile (INI-based):**
```
web: bash -lc 'mkdir -p configfiles && printf "%s\n" "$FETLIFE_INI" > configfiles/fetlife.ini && PYTHONPATH=publisher_v2/src uvicorn publisher_v2.web.app:app --host 0.0.0.0 --port $PORT'
```

**New Procfile (env-first):**
```
web: PYTHONPATH=publisher_v2/src uvicorn publisher_v2.web.app:app --host 0.0.0.0 --port $PORT
```

The INI file creation step is no longer required when all JSON env vars are set.

---

## Step-by-Step Migration Procedure

### Phase 1: Set New Config Vars (keep FETLIFE_INI for safety)

```bash
# 1. Set the three required JSON env vars
heroku config:set STORAGE_PATHS='{"root": "/Photos/MySocialMedia"}' -a YOUR_APP_NAME
heroku config:set PUBLISHERS='[{"type": "fetlife", "recipient": "user@fetlife.com"}]' -a YOUR_APP_NAME  
heroku config:set OPENAI_SETTINGS='{}' -a YOUR_APP_NAME

# 2. Set EMAIL_SERVER if using email publisher
heroku config:set EMAIL_SERVER='{"sender": "bot@gmail.com", "smtp_server": "smtp.gmail.com", "smtp_port": 587}' -a YOUR_APP_NAME

# 3. (Optional) Set other config vars
heroku config:set CONTENT_SETTINGS='{"archive": true}' -a YOUR_APP_NAME
```

### Phase 2: Validate

```bash
# Check app health
curl https://YOUR_APP_NAME.herokuapp.com/health

# Check web UI loads
open https://YOUR_APP_NAME.herokuapp.com/

# Check logs for any config errors
heroku logs --tail -a YOUR_APP_NAME
```

**Expected log output:**
```
Config source: env_vars
```

**If you see deprecation warnings:**
```
DEPRECATION: INI-based config is deprecated. Migrate to JSON env vars...
```
This means some config is still falling back to INI — add the missing JSON env vars.

### Phase 3: Remove FETLIFE_INI

```bash
# Remove the old config var
heroku config:unset FETLIFE_INI -a YOUR_APP_NAME
heroku config:unset CONFIG_PATH -a YOUR_APP_NAME

# Restart dyno to apply
heroku ps:restart -a YOUR_APP_NAME
```

### Phase 4: Final Validation

1. ✅ `/health` returns 200
2. ✅ Web UI loads at root URL
3. ✅ "Random image" button shows an image (Dropbox access works)
4. ✅ Admin login works (password or Auth0)
5. ✅ No `ConfigurationError` in logs
6. ✅ No deprecation warnings in logs

---

## Rollout Plan (Pipeline)

> Conservative approach: canary first, then batch rollout.

| Step | Action | Validation |
|------|--------|------------|
| 1 | Pick one canary app | — |
| 2 | Set new JSON config vars (keep FETLIFE_INI) | Restart and check logs |
| 3 | Validate canary | /health, web UI, Dropbox, admin |
| 4 | Remove FETLIFE_INI from canary | Restart and validate again |
| 5 | Roll forward to remaining apps (5-10 at a time) | Same validation per batch |
| 6 | Update Procfile in repo | Remove INI bootstrap step |
| 7 | Deploy updated Procfile | Pipeline promotion |

---

## Troubleshooting

### Error: `ConfigurationError: Either config_file_path must be provided or all required env vars must be set`

**Cause:** Missing one of the three required JSON env vars.

**Fix:** Ensure all three are set:
```bash
heroku config -a YOUR_APP_NAME | grep -E "STORAGE_PATHS|PUBLISHERS|OPENAI_SETTINGS"
```

### Error: `Invalid JSON in STORAGE_PATHS`

**Cause:** Malformed JSON syntax.

**Fix:** Validate your JSON at https://jsonlint.com/ before setting.

### Warning: `DEPRECATION: INI-based config is deprecated`

**Cause:** App is falling back to INI for some configuration.

**Fix:** Check which sections are mentioned and add the corresponding JSON env var.

### App boots but publishing fails

**Cause:** Publisher-specific secrets missing.

**Fix:** For each publisher type in `PUBLISHERS`, ensure its secret is set:
- Telegram → `TELEGRAM_BOT_TOKEN`
- FetLife → `EMAIL_PASSWORD` + `EMAIL_SERVER`
- Instagram → `INSTA_PASSWORD`

---

## Acceptance Criteria

- [x] Given a Heroku app has the Feature 021 env vars set, when it boots, then it no longer requires `FETLIFE_INI` to start successfully.
- [x] Given an app has `FETLIFE_INI` unset/removed, when it boots, then it still serves the web UI using env-first configuration.
- [x] Given a pipeline with N apps, when migration is executed following the documented rollout plan, then each app remains operational.
- [x] Given a developer updates their local `.env` following the documented mapping, when they run locally, then behavior matches the prior INI-driven configuration.

---

## See Also

- [CONFIGURATION.md Section 8: Env-First Configuration](../../../../../05_Configuration/CONFIGURATION.md#8-v2-env-first-configuration-feature-021)
- [CONFIGURATION.md Section 9: Migration Guide](../../../../../05_Configuration/CONFIGURATION.md#9-migration-guide)
- [dotenv.v2.example](../../../../../dotenv.v2.example) — Full example `.env` file


