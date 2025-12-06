<!-- docs_v2/08_Features/08_01_Feature_Request/011_heroku-hetzner-app-cloning.md -->

# Heroku App Cloning with Hetzner DNS Subdomain Automation

**ID:** 011  
**Name:** heroku-hetzner-app-cloning  
**Status:** Proposed  
**Date:** 2025-11-21  
**Author:** User Request  

## Summary
Add an automated, scriptable workflow to clone a reference Heroku app (`fetlife-prod`), provision a corresponding custom subdomain on Hetzner DNS under `shibari.photo`, and update per-instance configuration (notably the `image_folder` in the `FETLIFE_INI` config var).  
The workflow should be exposed as a simple CLI tool (Python) suitable for direct use and CI/CD integration, and should be robust, idempotent where possible, and extensible to additional PaaS or DNS providers in the future.

## Problem Statement
Today, provisioning a new instance of the FetLife publisher app involves several manual, error-prone steps:
- Cloning or forking the existing Heroku app (`fetlife-prod`) using the Heroku dashboard or CLI.
- Manually configuring environment variables, including inlining an updated `FETLIFE_INI` block with a different `[Dropbox].image_folder` path.
- Attaching a new Heroku custom domain that matches a desired subdomain under `shibari.photo`.
- Switching to Hetzner’s DNS UI or API to create a CNAME record for `<name>.shibari.photo` pointing to the new Heroku app’s target hostname.

This manual process is slow, hard to repeat consistently, and scales poorly when many isolated instances or tenants are needed.

## Goals
- Provide a single automated flow that:
  - Clones an existing Heroku app (`fetlife-prod`) into a new app with a caller-specified name.
  - Creates and associates a custom domain `<name>.shibari.photo` with the new Heroku app.
  - Creates or updates the corresponding DNS record in Hetzner DNS (CNAME or equivalent) pointing at the correct Heroku hostname.
  - Copies over config vars from the source app and updates the `FETLIFE_INI` config var’s `[Dropbox].image_folder` value to a caller-specified folder path.
- Expose this automation as a Python-based CLI tool (placed under `/scripts`) that can be called locally or from CI/CD/automation agents.
- Implement clear status reporting and error messages for each step (clone, domain, DNS, config).
- Keep secrets (Heroku API token, Hetzner DNS token) in environment variables or external config, never in code or committed files.

## Non-Goals
- Changing the internal behavior of the publisher V2 workflows or web UI; this feature focuses on infrastructure and deployment automation only.
- Implementing a generic multi-cloud deployment orchestrator; initial scope is Heroku + Hetzner DNS only.
- Providing a full lifecycle manager (e.g., automatic teardown of apps and DNS records) beyond basic scripting hooks that could be extended later.
- Managing Heroku add-on provisioning beyond what the Heroku fork/clone APIs already handle.

## Users & Stakeholders
- **Primary users**
  - The project maintainer deploying new isolated instances of the FetLife publisher app.
  - Power users or operators who need multiple per-tenant or per-environment clones with their own image folders and subdomains.
- **Stakeholders**
  - Future collaborators who may rely on consistent, scripted provisioning of new app instances.
  - CI/CD systems or automation agents (e.g., GPT-5.1 powered Cursor agents) that orchestrate deployments.

## User Stories
- As an operator, I want to run a single CLI command with a `name` so that a new Heroku app is cloned from `fetlife-prod`, a subdomain `<name>.shibari.photo` is provisioned, and DNS is configured correctly, without me touching the Heroku or Hetzner UIs.
- As an operator, I want to provide a folder path argument that is used to update the `image_folder` setting inside the `FETLIFE_INI` config var on the new Heroku app, so that each instance points at its own Dropbox folder.
- As an operator, I want the tool to fail fast with clear messages when cloning, domain creation, or DNS record creation fails, so I know which manual remediation is required.
- As an operator, I want the tool to be safely re-runnable for a given `name` (where possible), so that if DNS creation fails after the app is cloned, I can rerun the script to repair DNS and config instead of starting from scratch.
- As a maintainer, I want the tool to keep secrets in environment variables and support dry-run output where feasible, so that I can test configuration without making unintended changes.

## Acceptance Criteria (BDD-style)
- **Heroku app cloning**
  - Given a valid Heroku API token and an existing source app `fetlife-prod`, when I run the CLI with `--name example` and `--folder /Photos/example`, then the tool creates a new Heroku app (e.g., `fetlife-prod-example` or a predictable variant) cloned from `fetlife-prod` using the Heroku Platform API or CLI fork command, and reports the new app name and base URL.
  - Given the source app has an existing `FETLIFE_INI` config var, when cloning completes, then the tool reads that config var from the source app, updates the `[Dropbox].image_folder` value to `/Photos/example`, and sets the updated `FETLIFE_INI` value on the new app.

- **Heroku custom domain + Hetzner DNS**
  - Given the new app exists and I provide `--name example`, when the tool runs, then it registers a custom domain `example.shibari.photo` on the new Heroku app via the Heroku domains API and obtains the DNS target hostname.
  - Given a valid Hetzner DNS API token and an existing zone for `shibari.photo`, when the tool runs for `--name example`, then it creates (or updates) a CNAME record for `example` in the `shibari.photo` zone pointing to the Heroku-provided DNS target, and reports the resulting record.

- **Configuration and CLI**
  - Given I have exported the necessary environment variables (e.g., `HEROKU_API_TOKEN`, `HETZNER_DNS_API_TOKEN`) and I run `python scripts/<tool>.py --name example --folder /Photos/example`, then the command completes the clone + domain + DNS + config steps or fails with a clear error message indicating which phase failed.
  - Given I run the CLI with `--help`, then I see documented options for `--name`, `--folder`, optional flags (e.g., `--dry-run`, `--heroku-app-name-prefix`), and environment prerequisites.

## Technical Requirements
- Implement the automation as a Python script in `/scripts` that:
  - Uses the Heroku Platform API (or Heroku CLI via subprocess) to:
    - Clone/fork an existing app (`fetlife-prod`) into a new app.
    - Read and write config vars, including `FETLIFE_INI`.
    - Register a custom domain (`<name>.shibari.photo`) and retrieve its DNS target.
  - Uses the Hetzner DNS API to:
    - Look up the zone for `shibari.photo`.
    - Create or update a CNAME record for `<name>` pointing to the Heroku DNS target.
  - Accepts at least:
    - `--name` (subdomain + app instance identifier).
    - `--folder` (new `image_folder` value to embed into `FETLIFE_INI`).
  - Loads API tokens and other secrets from environment variables; supports a dry-run mode that prints the planned changes without calling the APIs where feasible.
- Keep the implementation modular (e.g., separate helpers for Heroku and Hetzner interactions) to allow possible extension to other providers.
- Include basic retry logic and structured logging for API calls.

## Dependencies
- Heroku Platform API and/or Heroku CLI installed in the environment where the script runs.
- Hetzner DNS API for DNS record management.
- Existing `FETLIFE_INI` config var and its `[Dropbox].image_folder` key on the `fetlife-prod` app.

## Risks & Mitigations
- **Risk:** Heroku fork/clone semantics may not perfectly replicate all add-ons or configuration, leading to subtle differences between instances.  
  **Mitigation:** Scope the tool to rely on documented Heroku cloning behavior; document any known limitations and surface clear logs about what was cloned vs. manually configured.

- **Risk:** Misconfigured DNS (wrong CNAME target or subdomain) could lead to inaccessible instances.  
  **Mitigation:** Fetch the canonical DNS target from Heroku’s domains API and avoid hard-coding hostnames; validate that the Hetzner record matches the expected target and log the final mapping.

- **Risk:** Incorrect updates to `FETLIFE_INI` could break the new instance’s Dropbox integration.  
  **Mitigation:** Parse and update only the `[Dropbox].image_folder` key, leaving other content untouched; validate that the updated INI parses correctly before setting it on the new app.

## Open Questions
- Should the tool support teardown (deleting the Heroku app and DNS record) as a first-class operation, or remain provision-only for now?
- Should the script support naming conventions or templates for the new app name (e.g., `fetlife-prod-<name>` vs. arbitrary `--app-name`), and how strict should validation be?
- Should the tool manage SSL certificate provisioning for the new custom domain explicitly, or rely on Heroku’s automatic certificate management?


