<!-- docs_v2/08_Features/08_04_ChangeRequests/011/001_servers-log.md -->

# Story 001 — Server Log File for Heroku/Hetzner Provisioning

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 001  
**Name:** servers-log  
**Status:** Proposed  
**Date:** 2025-11-21  
**Author:** Story Workflow  

## Summary

Add a simple, append-only `servers.txt` log file under the `/scripts` folder that tracks each newly provisioned Heroku app instance created by `heroku_hetzner_clone.py`.  
Each successful run that completes the full provisioning flow should append a single line containing: the logical name, Dropbox image folder, Heroku URL, subdomain URL, and creation timestamp.  
The `servers.txt` file must be ignored by Git (added to `.gitignore`) so that environment-specific server lists are never committed.

## Problem Statement

The `heroku_hetzner_clone.py` script automates creating new Heroku apps, assigning Hetzner DNS subdomains, and updating configuration, but there is currently no simple, persistent record of which instances have been created over time.  
Operators must rely on Heroku’s dashboard and Hetzner DNS UI to reconstruct which `--name`/`--folder` combinations were used and which subdomain maps to which app.  
This makes it harder to audit deployments, track per-tenant instances, or quickly reference the mapping between logical names, folders, Heroku URLs, and subdomain URLs.

## Goals

- Maintain a lightweight, human-readable log file `scripts/servers.txt` that:
  - Is updated on each successful provisioning run of `heroku_hetzner_clone.py`.
  - Records for each instance:
    - `name` (CLI `--name` argument).
    - `folder` (CLI `--folder` argument).
    - Heroku app URL.
    - Subdomain URL (`https://<name>.shibari.photo`).
    - Creation timestamp in a standard format (UTC).
- Ensure `servers.txt` is ignored by Git and never accidentally committed.
- Keep the implementation small, robust, and side-effect free in dry-run mode.

## Non-Goals

- Implementing a full database or structured registry of servers.
- Adding a web UI or CLI to query or mutate `servers.txt`.
- Retroactively populating the log for previously created instances.
- Changing the existing provisioning flow or configuration semantics.

## Acceptance Criteria

- **Logging behavior**
  - Given I run `heroku_hetzner_clone.py` successfully (non-dry-run) with `--name tati` and `--folder /Photos/tati`, when the script completes all steps (app creation, config, domain, DNS, promotion), then `scripts/servers.txt` exists and contains a new line with five comma- or tab-separated fields: `tati`, `/Photos/tati`, the Heroku URL, the subdomain URL, and an ISO-like UTC timestamp.
  - Given `scripts/servers.txt` already exists, when I provision another server, then the script appends a new line and does not rewrite or truncate existing lines.

- **Dry-run safety**
  - Given I run `heroku_hetzner_clone.py` with `--dry-run`, when the script exits, then no `servers.txt` file is created or modified.

- **Git ignore**
  - Given `.gitignore` is configured for this repo, when I run `git status`, then `scripts/servers.txt` does not show up as an untracked or modified file, even after multiple provisioning runs.

## Dependencies

- Parent feature design: `docs_v2/08_Features/08_02_Feature_Design/011_heroku-hetzner-app-cloning_design.md`.
- Existing provisioning script: `scripts/heroku_hetzner_clone.py`.
- Repository-level ignore rules: `.gitignore`.


