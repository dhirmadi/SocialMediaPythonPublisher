# Story: Heroku Pipeline Migration (Stop Using `FETLIFE_INI`)

**Feature ID:** 021  
**Story ID:** 021-07  
**Name:** heroku-pipeline-migration  
**Status:** Proposed  
**Date:** 2025-12-23  
**Parent Feature:** 021_config_env_consolidation

## Summary

Migrate the **Heroku `fetlife` pipeline** off the `FETLIFE_INI` config-var/bootstrap approach and onto the **env-first consolidated configuration** introduced by Feature 021.

This story produces a **repeatable rollout procedure** so that:
- all apps/instances in the `fetlife` pipeline can be migrated safely and consistently
- local development can be migrated via an updated `.env` template and clear instructions

## Background / Motivation

Today the Heroku deployment uses a `FETLIFE_INI` config var to write an INI file at dyno startup (via `Procfile`). Feature 021’s goal is to make configuration **env-first** (and ultimately orchestrator-sourced), so we should stop depending on INI for Heroku runtime configuration.

## Scope

- Provide the **deployment-time instructions** to migrate all apps in the `fetlife` pipeline:
  - required env vars (secrets + non-secrets)
  - which existing env vars become obsolete
  - recommended rollout order and verification steps
- Define required changes to the Heroku runtime bootstrap:
  - `Procfile` / startup command should no longer depend on `FETLIFE_INI`
  - `CONFIG_PATH` / INI requirements must not block the web app once env-first loading is active
- Provide local migration guidance:
  - `.env` template updates
  - mapping from INI fields to new env vars

## Out of Scope

- Implementing the orchestrator API runtime config calls (Epic 001).
- Changing business logic (publish/analyze/archive behavior).

## Required Environment Variables (Heroku)

### Secrets (flat env vars)
- `OPENAI_API_KEY`
- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REFRESH_TOKEN`
- Optional publisher secrets:
  - `TELEGRAM_BOT_TOKEN`
  - `EMAIL_PASSWORD`
  - `INSTA_PASSWORD`

### Non-secrets (JSON groupings)
- `STORAGE_PATHS`
- `PUBLISHERS`
- `EMAIL_SERVER` (when Email/FetLife publisher is enabled)
- `OPENAI_SETTINGS` (optional overrides; otherwise defaults/INI fallback)
- `CAPTIONFILE_SETTINGS` (optional)
- `CONFIRMATION_SETTINGS` (optional)
- `CONTENT_SETTINGS` (optional; recommended for parity)

### Deprecated / to be removed from Heroku apps after migration
- `FETLIFE_INI` (primary target of this story)

## Acceptance Criteria

- Given a Heroku app in the `fetlife` pipeline has the Feature 021 env vars set, when it boots, then it no longer requires `FETLIFE_INI` to start successfully.
- Given an app has `FETLIFE_INI` unset/removed, when it boots, then it still serves the web UI and can perform configured actions using the env-first configuration.
- Given a pipeline with N apps, when migration is executed following the documented rollout plan, then each app remains operational and configuration is consistent across the pipeline.
- Given a developer updates their local `.env` following the documented mapping, when they run locally, then behavior matches the prior INI-driven configuration.

## Rollout Plan (Pipeline)

> This is intentionally conservative for non-prod and scales to prod later.

1. **Pick one canary app** in the `fetlife` pipeline.
2. Set the new config vars on the canary app (leave `FETLIFE_INI` in place for first boot if desired).
3. Validate:
   - `/health` returns 200
   - web UI loads
   - “random image” works (Dropbox access)
   - admin login works (Auth0)
4. Remove `FETLIFE_INI` from the canary app and restart dyno.
5. Validate again.
6. Roll forward to remaining pipeline apps (batching 5–10 at a time).

## Local Migration Instructions (Developer)

1. Copy `dotenv.example` (or new template) to `.env`.
2. Set required secrets (OpenAI, Dropbox, publisher secrets as needed).
3. Replace INI config with env-first vars:
   - Build `STORAGE_PATHS` from `[Dropbox]` section
   - Build `PUBLISHERS` from `[Content]` toggles + publisher sections
   - Build `EMAIL_SERVER` from `[Email]` + `EMAIL_PASSWORD`
   - Set `CONTENT_SETTINGS` from `[Content]` (hashtag_string/archive/debug)
4. Run and confirm parity in preview mode.

## Notes / Implementation Dependencies

This story depends on the Feature 021 implementation ensuring:
- The **web runtime** can load configuration without requiring an INI file generated at boot.
- Any remaining INI fallback logic does not block when `FETLIFE_INI` is removed.


