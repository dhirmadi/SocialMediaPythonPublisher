<!-- docs_v2/08_Features/011_heroku-hetzner-app-cloning.md -->

# Heroku App Cloning with Hetzner DNS Subdomain Automation — Shipped Feature

**ID:** 011  
**Name:** heroku-hetzner-app-cloning  
**Status:** Shipped  
**Date:** 2025-11-21  
**Author:** User Request  

## Summary

This feature adds a standalone Python CLI script under `/scripts` that automates provisioning a new instance of the FetLife publisher Heroku app with a dedicated subdomain and Dropbox image folder.  
Given a logical instance name (`--name`) and a Dropbox image folder path (`--folder`), the script:
- Clones the reference Heroku app `fetlife-prod` using the Heroku Platform API.
- Copies all config vars from the source app and rewrites the `[Dropbox].image_folder` value inside the `FETLIFE_INI` config var for the new app.
- Registers a Heroku custom domain `<name>.shibari.photo` on the new app and retrieves the DNS target.
- Ensures a corresponding CNAME record in the Hetzner DNS `shibari.photo` zone that points `<name>` to the Heroku DNS target.

The core V2 runtime (workflow, web UI, config loaders) is unchanged; the script is an operator tool for faster, safer multi-instance provisioning.

## Goals

- Automate the previously manual workflow of cloning the `fetlife-prod` Heroku app, configuring per-instance settings, and wiring up DNS in Hetzner.
- Provide a simple, documented CLI that can be invoked locally or from CI/automation agents.
- Keep secrets in environment variables (`HEROKU_API_TOKEN`, `HETZNER_DNS_API_TOKEN`) and avoid any impact on the running V2 application.

## Non-Goals

- Changing publisher V2 runtime behavior, configuration schema, or web UI.
- Implementing teardown (deleting apps or DNS records) or managing SSL certificates beyond Heroku’s own automation.
- Supporting non-Heroku or non-Hetzner providers in this iteration.

## User Value

Operators no longer need to:
- Manually fork apps from the Heroku dashboard or CLI.
- Hand-edit embedded `FETLIFE_INI` config content to tweak `[Dropbox].image_folder`.
- Jump between Heroku and Hetzner UIs to wire up custom domains and DNS.

Instead, they can run a single command that performs all of these steps with clear logs and error messages, making it feasible to manage many staging, tenant, or experimental instances with consistent configuration.

## Technical Overview

- **Script location:** `/scripts/heroku_hetzner_clone.py`  
- **Key responsibilities:**
  - Input parsing via `argparse`:
    - `--action` (optional, default `create`):  
      - `create` → provision a new app and DNS entry.  
      - `delete` → delete an existing app/DNS entry based on `servers.txt`.
    - `--name` (required): logical instance identifier; used for:
      - Heroku app name `fetlife-prod-<name>` (unless `--heroku-app-name` is provided).
      - Subdomain `<name>.shibari.photo`.
      - CNAME record name in Hetzner.
    - `--folder` (required for `create` non-dry-run): injected into `FETLIFE_INI` as `[Dropbox].image_folder`.
    - `--password` (required for `create` non-dry-run): sets `web_admin_pw` in the new app’s config, used by the web admin auth.
    - `--heroku-source-app` (optional, default `fetlife-prod`): source app for config vars and `FETLIFE_INI`.
    - `--heroku-staging-app` (optional, default `fetlife`): staging app whose slug is promoted via pipelines.
    - `--pipeline` / `--pipeline-stage` (optional, default `fetlife` / `production`): target pipeline and stage for the new app.
    - `--heroku-app-name` (optional explicit app name override).
    - `--dry-run` (optional: plan-only mode without API calls or file writes).
  - Heroku integration (`HerokuClient`):
    - `POST /apps` to create a new blank app (no direct fork endpoint is used).
    - `GET /apps/{app}/config-vars` and `PATCH /apps/{app}/config-vars` to clone and update config vars (`FETLIFE_INI`, feature flags, `AUTO_VIEW`, `web_admin_pw`, etc.).
    - `POST /apps/{app}/acm` to enable Automated Certificate Management (ACM).
    - `POST /apps/{app}/domains` with `{"hostname": "<name>.shibari.photo", "sni_endpoint": null}` to create the custom domain and capture the DNS target.
    - `GET /pipelines` and `POST /pipeline-couplings` to add the new app to the `fetlife` pipeline.
    - `POST /pipeline-promotions` to promote the current slug from the staging app to the new app.
    - `DELETE /apps/{app}` to delete apps in the `delete` flow.
  - Hetzner DNS integration (`HetznerDNSClient`):
    - `GET /zones?name=shibari.photo` to resolve the zone.
    - `GET /records?zone_id=...&name=...&type=CNAME` plus `POST /records` / `PUT /records/{id}` to create or update the CNAME for `<name>`.
    - `DELETE /records/{id}` to remove the CNAME in the `delete` flow.
  - INI mutation helper:
    - `update_image_folder(ini_text: str, new_folder: str) -> str`:
      - Parses the `FETLIFE_INI` string with `configparser`.
      - Validates presence of `[Dropbox]` and `image_folder`.
      - Sets the new folder value and validates the result is parseable.
  - Local server log:
    - `scripts/servers.txt` (ignored by Git) is updated on successful `create` runs with:
      - `name,folder,heroku_url,subdomain_url,created_at_utc`.
    - `delete` runs read and prune entries from this file.

Errors from Heroku or Hetzner APIs are wrapped in small custom exceptions (`HerokuError`, `HetznerDNSError`) and surfaced with phase-specific messages; the script exits non-zero on failure. File logging failures are surfaced as warnings only.

## Implementation Details

- **Heroku app naming**
  - Default new app name uses the fixed pattern `fetlife-prod-<name>`, normalized for Heroku rules (lowercase, letters/numbers/dashes only, leading letter, length ≤ 30).
  - Operators can override the exact app name via `--heroku-app-name` if desired.

- **Subdomain validation**
  - The `--name` argument is validated as a DNS label:
    - Allowed characters: letters, digits, `-`.
    - No leading or trailing `-`.
  - The resulting hostname is `<name>.shibari.photo`.

- **FETLIFE_INI handling**
  - The script expects the source app (`fetlife-prod` by default) to have a `FETLIFE_INI` config var.
  - `update_image_folder`:
    - Raises `ValueError` if `[Dropbox]` or `image_folder` is missing or if `new_folder` is empty.
    - Writes back the INI content and re-parses it to ensure validity before applying it to the new app.

- **DNS configuration**
  - After creating the Heroku domain, the script:
    - Extracts a DNS target from the response (`cname`, `dns_target`, or `hostname` as a fallback).
    - Fetches the Hetzner zone for `shibari.photo`.
    - Calls `ensure_cname` to:
      - Find any existing CNAME for `<name>` in that zone.
      - Update it if present, otherwise create a new record.

  - In addition, several config vars are normalized on new apps:
    - `FEATURE_KEEP_CURATE=true`
    - `FEATURE_REMOVE_CURATE=true`
    - `FEATURE_ANALYZE_CAPTION=false`
    - `FEATURE_PUBLISH=false`
    - `AUTO_VIEW=false`
    - `web_admin_pw=<--password value>`

- **Dry-run mode**
  - With `--dry-run`, the script:
    - Prints the derived new app name, subdomain, folder, and action.
    - Skips all external API calls and file writes (no apps, domains, DNS, or `servers.txt` changes).

- **Delete mode**
  - With `--action delete --name <name>`:
    - The script reads `scripts/servers.txt` to find records whose `name` matches.
    - In dry-run, it prints what would be deleted (apps, DNS) without making changes.
    - In normal mode, it:
      - Parses the Heroku app name from the stored Heroku URL and calls `DELETE /apps/{app}`.
      - Removes the corresponding Hetzner CNAME for `<name>.shibari.photo`.
      - Rewrites `scripts/servers.txt` to remove the matching line(s).

## Testing

- **Automated tests**
  - New tests added in `publisher_v2/tests/test_scripts_heroku_hetzner_clone.py` cover:
    - Successful update of `[Dropbox].image_folder` while preserving other sections/keys.
    - Failure cases when the [Dropbox] section or `image_folder` key is missing.
  - Tests dynamically import the script module from `/scripts` to avoid coupling it to the main package.

- **Manual validation (recommended)**
  - Run against a non-production Heroku app and a test Hetzner zone to verify:
    - App clone appears in Heroku (`heroku apps:info`).
    - Config vars are cloned and `FETLIFE_INI` reflects the new folder.
    - `<name>.shibari.photo` is created under the new app’s domains.
    - Hetzner DNS CNAME for `<name>` points to the Heroku DNS target.

## Rollout Notes

- This feature is fully additive:
  - No changes were made to `publisher_v2` application runtime code or configuration schema.
  - Existing deployments continue to run unchanged.
- Operators can start using the script immediately after it is available in the repo:
  - Ensure `HEROKU_API_TOKEN` and `HETZNER_DNS_API_TOKEN` are set in the environment.
  - Run (create):  
    - `python scripts/heroku_hetzner_clone.py --name myinstance --folder /Photos/myinstance --password <admin-password>`
  - Run (delete):  
    - `python scripts/heroku_hetzner_clone.py --action delete --name myinstance`
- If any issues arise, simply stop using the script; there is no impact on the core system beyond any apps/DNS records already created (which can be managed manually via Heroku/Hetzner UIs as before).

## Artifacts

- Feature Request: `docs_v2/08_Features/08_01_Feature_Request/011_heroku-hetzner-app-cloning.md`  
- Feature Design: `docs_v2/08_Features/08_02_Feature_Design/011_heroku-hetzner-app-cloning_design.md`  
- Implementation Plan: `docs_v2/08_Features/08_03_Feature_plan/011_heroku-hetzner-app-cloning_plan.yaml`  
- Implementation:
  - Script: `/scripts/heroku_hetzner_clone.py`
  - Tests: `publisher_v2/tests/test_scripts_heroku_hetzner_clone.py`
- Final Feature Doc: `docs_v2/08_Features/011_heroku-hetzner-app-cloning.md` (this file)


