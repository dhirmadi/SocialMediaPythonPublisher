# PUB-011: Heroku App Cloning with Hetzner DNS Subdomain Automation

| Field | Value |
|-------|-------|
| **ID** | PUB-011 |
| **Category** | Ops |
| **Priority** | INF |
| **Effort** | L |
| **Status** | Done |
| **Dependencies** | — |

## Problem

Today, provisioning a new instance of the FetLife publisher app involves several manual, error-prone steps: cloning or forking the existing Heroku app (`fetlife-prod`) via dashboard or CLI, manually configuring environment variables and inlining an updated `FETLIFE_INI` block with a different `[Dropbox].image_folder` path, attaching a new Heroku custom domain, and switching to Hetzner's DNS UI or API to create a CNAME record for `<name>.shibari.photo`. This manual process is slow, hard to repeat consistently, and scales poorly when many isolated instances or tenants are needed.

## Desired Outcome

A single automated flow that clones `fetlife-prod` into a new app with a caller-specified name, creates and associates a custom domain `<name>.shibari.photo`, creates or updates the corresponding DNS record in Hetzner DNS, and copies config vars while updating `FETLIFE_INI`'s `[Dropbox].image_folder` to a caller-specified folder path. Exposed as a Python-based CLI tool under `/scripts` suitable for local use and CI/CD integration.

## Scope

- Clone source app `fetlife-prod` into new app (e.g., `fetlife-prod-<name>`)
- Register custom domain `<name>.shibari.photo` on new Heroku app; obtain DNS target
- Create/update CNAME record in Hetzner DNS zone for `shibari.photo` pointing to Heroku DNS target
- Copy config vars; parse and update only `[Dropbox].image_folder` in `FETLIFE_INI`
- CLI args: `--name`, `--folder`; optional `--dry-run`, `--heroku-app-name-prefix`
- Secrets in env vars: `HEROKU_API_TOKEN`, `HETZNER_DNS_API_TOKEN`
- Idempotent where possible; clear status reporting and error messages per step

## Acceptance Criteria

- AC1: Given valid Heroku API token and source app `fetlife-prod`, when I run the CLI with `--name example` and `--folder /Photos/example`, the tool creates a new Heroku app cloned from `fetlife-prod`, updates `FETLIFE_INI`'s `image_folder` to `/Photos/example`, and reports the new app name and base URL
- AC2: Given the new app exists and `--name example`, the tool registers custom domain `example.shibari.photo` and obtains the DNS target hostname
- AC3: Given valid Hetzner DNS API token and zone for `shibari.photo`, the tool creates or updates a CNAME record for `example` pointing to the Heroku DNS target
- AC4: Given env vars exported and CLI run, the command completes all steps or fails with a clear error indicating which phase failed
- AC5: Given `--help`, documented options for `--name`, `--folder`, and optional flags are shown

## Implementation Notes

- Python script in `/scripts`; modular helpers for Heroku and Hetzner interactions
- Heroku Platform API or CLI for clone, config vars, and domains
- Hetzner DNS API for zone lookup and CNAME create/update
- Parse and update only `[Dropbox].image_folder` in INI; validate updated INI before setting on new app
- Basic retry logic and structured logging for API calls

## Related

- [Original feature doc](../../08_Epics/004_deployment_ops_modernization/011_heroku_hetzner_app_cloning/011_feature.md) — full historical detail
