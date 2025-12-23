# Story Summary: Heroku Pipeline Migration

**Feature ID:** 021  
**Story ID:** 021-07  
**Status:** Shipped  
**Date Completed:** 2025-12-23

## Summary

Documented the migration procedure for Heroku `fetlife` pipeline apps to transition from `FETLIFE_INI` config var bootstrap to the env-first configuration model introduced by Feature 021.

## Files Changed

### Documentation
- `docs_v2/08_Features/021_config_env_consolidation/stories/07_heroku_pipeline_migration/021_07_heroku-pipeline-migration.md` — Story definition with:
  - Required environment variables (secrets + non-secrets)
  - Deprecated variables to remove after migration
  - Conservative rollout plan for pipeline migration
  - Local developer migration instructions

- `docs_v2/05_Configuration/CONFIGURATION.md` — Added Heroku migration section (Section 9.3) with:
  - Step-by-step Heroku migration procedure
  - Reference link to detailed story documentation

- `dotenv.v2.example` — Includes deprecation notes for:
  - `CONFIG_PATH` (old INI approach)
  - `FETLIFE_INI` (primary target of migration)

## Implementation Notes

This story is primarily documentation-focused. The technical infrastructure for env-first configuration was implemented in Stories 01-06. Story 07 provides:

1. **Operator Guidance**: Clear instructions for migrating Heroku apps
2. **Rollout Safety**: Conservative canary-first approach
3. **Validation Steps**: Specific checks (health, web UI, Dropbox, admin login)
4. **Rollback Option**: Keep FETLIFE_INI during initial migration for safety

## Acceptance Criteria Status

- [x] AC1: Given Feature 021 env vars are set, app can boot without FETLIFE_INI
- [x] AC2: Given FETLIFE_INI is removed, app serves web UI using env-first config
- [x] AC3: Documented rollout plan for pipeline with N apps
- [x] AC4: Documented local .env migration for developers

## Rollout Plan Summary

1. **Canary**: Pick one app in fetlife pipeline
2. **Configure**: Set new env vars (keep FETLIFE_INI initially)
3. **Validate**: /health, web UI, Dropbox access, admin login
4. **Remove**: Unset FETLIFE_INI, restart dyno
5. **Validate Again**: Confirm app works without INI
6. **Roll Forward**: Batch remaining apps (5-10 at a time)

## Follow-up Items

- Execute the documented migration on production Heroku pipeline
- Monitor deprecation warnings during migration period
- Remove FETLIFE_INI bootstrap from Procfile after full migration

## Artifacts

- Story Definition: 021_07_heroku-pipeline-migration.md
- Story Design: 021_07_design.md
- Story Plan: 021_07_plan.yaml

