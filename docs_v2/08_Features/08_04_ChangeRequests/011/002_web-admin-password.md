<!-- docs_v2/08_Features/08_04_ChangeRequests/011/002_web-admin-password.md -->

# Story 002 — CLI Web Admin Password Parameter

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 002  
**Name:** web-admin-password  
**Status:** Proposed  
**Date:** 2025-11-21  
**Author:** Story Workflow  

## Summary

Extend the `heroku_hetzner_clone.py` CLI to require a `--password` argument that sets the `web_admin_pw` environment variable on the newly created Heroku app.  
This ensures each provisioned instance has an explicit, operator-chosen web admin password to protect the V2 web interface’s admin mode.

## Problem Statement

Today, the `heroku_hetzner_clone.py` provisioning script clones config vars from the source app and updates `FETLIFE_INI`, but it does not enforce or provision a web admin password for the new instance.  
The web layer (`publisher_v2.web.auth.get_admin_password`) expects `web_admin_pw` in the environment to enable admin mode; if this is missing or left empty, admin mode is effectively disabled or misconfigured.  
Relying on operators to manually set `web_admin_pw` after provisioning is error-prone and undermines the security posture of the web interface.

## Goals

- Add a mandatory CLI parameter `--password` to `scripts/heroku_hetzner_clone.py` that:
  - Is required for non-dry-run executions.
  - Represents the desired web admin password for the new instance.
- When cloning config vars to the new app:
  - Set or overwrite the `web_admin_pw` config var on the new Heroku app with the provided password value.
- Keep dry-run behavior safe (no config changes, no requirement to supply a real password).

## Non-Goals

- Changing the web auth or admin cookie semantics in `publisher_v2.web.auth`.
- Introducing password strength validation, rotation policies, or password storage beyond Heroku config vars.
- Masking or encrypting the password in local shell history (this remains an operator responsibility).

## Acceptance Criteria

- **CLI behavior**
  - Given I run `python scripts/heroku_hetzner_clone.py --help`, then the usage shows a required `--password` argument describing that it sets `web_admin_pw` for the new app’s admin mode.
  - Given I run the script without `--password` in non-dry-run mode, then argument parsing fails with a clear error and the script exits without making API calls.
  - Given I run the script with `--dry-run`, then I may omit `--password` (or supply a dummy), and no config vars are written to any app.

- **Config var behavior**
  - Given the source app `fetlife-prod` has its own config vars and I provision a new app with `--password secret123`, when config vars are cloned to the new app, then:
    - All existing config vars from `fetlife-prod` are copied (as today, with updated `FETLIFE_INI` and feature flags).
    - The new app has a `web_admin_pw` config entry set to `secret123` regardless of whether the source app had `web_admin_pw` configured.
  - Given the source app already has a `web_admin_pw` config var, when I provision a new app with `--password newpass`, then the new app’s `web_admin_pw` value is `newpass` (the CLI value wins).

## Dependencies

- Parent feature design: `docs_v2/08_Features/08_02_Feature_Design/011_heroku-hetzner-app-cloning_design.md`.  
- Web admin auth: `publisher_v2/src/publisher_v2/web/auth.py` (`get_admin_password` expects `web_admin_pw`).  
- Provisioning script: `scripts/heroku_hetzner_clone.py`.  


