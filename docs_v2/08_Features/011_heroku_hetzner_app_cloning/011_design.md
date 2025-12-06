<!-- docs_v2/08_Features/08_02_Feature_Design/011_heroku-hetzner-app-cloning_design.md -->

# Heroku App Cloning with Hetzner DNS Subdomain Automation — Feature Design

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Design Version:** 1.0  
**Date:** 2025-11-21  
**Status:** Design Review  
**Author:** Architecture Team  

---

## 1. Summary

### Problem
Provisioning new instances of the FetLife publisher app currently requires multiple manual steps across Heroku and Hetzner DNS:
- Cloning the `fetlife-prod` Heroku app (code, config vars, add-ons, collaborators).
- Updating instance-specific environment variables, especially the embedded `FETLIFE_INI` content (e.g., `[Dropbox].image_folder`).
- Adding a new custom domain on Heroku (e.g., `<name>.shibari.photo`) and configuring DNS in Hetzner to point at the correct Heroku target.

This is slow, error-prone, and difficult to scale to many instances or tenants.

### Goals
1. Provide a Python-based CLI tool under `/scripts` that automates:
   - Cloning a reference Heroku app (`fetlife-prod`) into a new app.
   - Adding a Heroku custom domain `<name>.shibari.photo` to the new app.
   - Creating/updating a matching Hetzner DNS record in the `shibari.photo` zone.
   - Copying config vars and mutating `FETLIFE_INI`’s `[Dropbox].image_folder` to a caller-specified folder.
2. Make the tool suitable for both local use and CI/CD/automation agents, with clear logging, error handling, and optional dry-run support.
3. Keep secrets out of the repository by sourcing API tokens from environment variables.
4. Keep the implementation modular and self-contained, without impacting V2 application runtime behavior.

### Non-Goals
- Changing publisher V2 runtime semantics (core workflow, web UI, config loader, etc.).
- Managing lifecycle teardown (deleting apps/DNS) beyond potential future extensions.
- Supporting non-Heroku or non-Hetzner providers in this iteration.
- Implementing a generalized infrastructure-as-code system; this is a focused provisioning helper.

---

## 2. Context & Assumptions

### Current State
- The repository already uses:
  - Heroku for deploying the V2 app (e.g., via `Procfile` and `runtime.txt`).
  - Dropbox as storage and `.ini`-based configuration (`configfiles/fetlife.ini`).
- Sample `fetlife.ini`:
  - Includes `[Dropbox].image_folder = /Photos/bondage_fetlife` and other settings.
  - Mirrors the embedded `FETLIFE_INI` config var used on Heroku.
- No existing automation in this repo manages Heroku apps or Hetzner DNS; such scripts will be new and live under `/scripts`.
- V2 design rules emphasize:
  - Keeping secrets out of code (`.env` and environment variables only).
  - Small, focused tools; avoid overengineering or tight coupling to core app code.

### Assumptions
1. Heroku account has:
   - A reference app named `fetlife-prod`.
   - Sufficient permissions for the API token to fork apps, read/set config vars, and manage domains.
2. Hetzner DNS account has:
   - A zone for `shibari.photo`.
   - An API token that can list zones and manage records.
3. For simplicity and robustness:
   - The tool will use the Heroku Platform API directly via `requests` (no new large dependencies), though it may optionally fall back to Heroku CLI for fork if needed.
   - The Heroku fork endpoint (`/apps/{source}/actions/fork`) will be used where possible, as it clones config vars and add-ons.
4. The `FETLIFE_INI` config var:
   - Exists on `fetlife-prod`.
   - Contains a `[Dropbox]` section with an `image_folder` key consistent with the sample INI file.
5. The script will be run from a developer or CI environment where:
   - Python 3.9+ is available.
   - Network access to Heroku and Hetzner DNS APIs is permitted.

---

## 3. Requirements

### Functional Requirements

**FR1: Heroku app cloning**
- Provide a function to clone `fetlife-prod` into a new Heroku app:
  - Input: `target_name` (logical instance name), optional `heroku_app_name` override.
  - Output: new Heroku app identifier and base `herokuapp.com` URL.
- Use the Heroku Platform API fork endpoint if available:
  - `POST /apps/{source-app}/actions/fork` with a new name.
  - On success, wait/poll until the new app is ready (or base URL is known).
- If fork is not available or fails fast with clear message, surface an actionable error.

**FR2: Config var cloning and FETLIFE_INI mutation**
- After cloning:
  - Read config vars from the source app (`fetlife-prod`) via Heroku API.
  - Ensure `FETLIFE_INI` is present and parseable as INI.
  - Update `[Dropbox].image_folder` to the `--folder` argument provided to the CLI.
  - Set all config vars on the new app, including the mutated `FETLIFE_INI`.
- Validate the updated INI parses cleanly before applying it.

**FR3: Heroku custom domain creation**
- For a given `name` and base domain `shibari.photo`:
  - Register a new custom domain `<name>.shibari.photo` on the new Heroku app via:
    - `POST /apps/{new-app-id}/domains` with `{ "hostname": "<name>.shibari.photo" }`.
  - Parse the response to obtain the Heroku DNS target hostname (e.g., `example.herokudns.com`).
  - Optionally, poll until domain status is `pending` or `active` as per Heroku docs, but do not overcomplicate.

**FR4: Hetzner DNS record management**
- Using Hetzner DNS API:
  - Look up the zone for `shibari.photo`.
  - Create a CNAME record with:
    - `name = <name>`
    - `type = "CNAME"`
    - `value = <heroku_dns_target>`
  - If a record for that subdomain already exists:
    - Optionally update it in-place instead of failing, unless a `--no-overwrite` flag is set.

**FR5: CLI interface**
- Implement a CLI entry in `/scripts` (e.g., `heroku_hetzner_clone.py`) that:
  - Accepts:
    - `--name` (required): logical instance + subdomain name.
    - `--folder` (required): new `[Dropbox].image_folder` value to inject into `FETLIFE_INI`.
    - Optional:
      - `--heroku-source-app` (default `fetlife-prod`).
      - `--heroku-app-name` (explicit app name override; otherwise derive).
      - `--dry-run` (print planned actions without making API calls where feasible).
  - Reads:
    - `HEROKU_API_TOKEN` from environment (Bearer token).
    - `HETZNER_DNS_API_TOKEN` from environment.
  - Performs steps in order:
    1. Clone app.
    2. Clone/mutate config vars.
    3. Create Heroku custom domain.
    4. Create/patch Hetzner DNS record.
  - Exits with non-zero status on failure, printing a concise error summary.

### Non-Functional Requirements
- **Security**
  - Never log full tokens or sensitive config values.
  - `FETLIFE_INI` content should only be manipulated in memory; avoid writing to disk.
- **Robustness**
  - Use lightweight retry behavior for transient HTTP errors (e.g., 5xx, timeouts).
  - Provide clear phase-specific error messages (clone vs config vs domain vs DNS).
- **Simplicity**
  - Keep the script self-contained and avoid coupling it to `publisher_v2` runtime modules.
  - Prefer small helper classes/functions over complex object graphs.

---

## 4. Architecture & Design

### 4.1 High-Level Flow

1. **Input & validation**
   - Parse CLI arguments (`--name`, `--folder`, etc.).
   - Validate `name` (DNS-safe subdomain label) and `folder` (non-empty string).
2. **Heroku app clone**
   - Call Heroku API fork endpoint to clone `fetlife-prod` into `new_app_name`:
     - Default scheme: `new_app_name = f"{source_app}-{name}"`, normalized to Heroku app name rules.
3. **Config var replication & mutation**
   - Fetch config vars for `source_app`.
   - Extract and parse `FETLIFE_INI` as INI.
   - Update `[Dropbox].image_folder = folder`.
   - Write updated `FETLIFE_INI` back into the config dict.
   - Set config vars on `new_app_name` via Heroku API.
4. **Custom domain creation**
   - POST Heroku domains API to create `<name>.shibari.photo`.
   - Capture `cname` or `dns_target` from the response.
5. **Hetzner DNS CNAME**
   - Find `shibari.photo` zone via Hetzner API.
   - Create/patch a CNAME record `name=<name>` pointing to the Heroku DNS target.
6. **Reporting**
   - Print a clear summary:
     - New app name.
     - Heroku base URL.
     - Custom domain hostname.
     - Hetzner DNS record created/updated.

### 4.2 Module & Class Structure

The script will live at:
- `/scripts/heroku_hetzner_clone.py`

Key components:

- **`HerokuClient`** (simple helper class)
  - Initialized with `api_token` and optional base URL.
  - Methods:
    - `fork_app(source_app: str, new_name: str) -> Dict[str, Any]`
    - `get_config_vars(app_name: str) -> Dict[str, str]`
    - `set_config_vars(app_name: str, config: Dict[str, str]) -> None`
    - `create_domain(app_name: str, hostname: str) -> Dict[str, Any]`
  - Uses `requests` with bearer token.

- **`HetznerDNSClient`**
  - Initialized with `api_token` and base URL (`https://dns.hetzner.com/api/v1`).
  - Methods:
    - `get_zone(domain: str) -> Dict[str, Any]`
    - `ensure_cname(zone_id: str, name: str, target: str, overwrite: bool = True) -> Dict[str, Any]`

- **`FetlIfeIniMutator`** (utility function)
  - Function `update_image_folder(ini_text: str, new_folder: str) -> str`:
    - Uses `configparser.ConfigParser` with `read_string`.
    - Updates `[Dropbox].image_folder`.
    - Writes back to string via `io.StringIO`.

- **`main()`**
  - Orchestrates CLI parsing and calls into the above helpers.

### 4.3 Heroku API Usage

- **Base**
  - URL: `https://api.heroku.com`
  - Headers:
    - `Authorization: Bearer <HEROKU_API_TOKEN>`
    - `Accept: application/vnd.heroku+json; version=3`

- **Fork app**
  - `POST /apps/{source-app}/actions/fork`
  - Body:
    - `{ "name": "<new-app-name>" }`
  - Response:
    - Includes new app UUID, name, and other metadata.

- **Config vars**
  - `GET /apps/{app-name}/config-vars`
  - `PATCH /apps/{app-name}/config-vars`
    - Body: full or partial config vars as JSON object.

- **Domains**
  - `POST /apps/{app-name}/domains`
    - Body: `{ "hostname": "<name>.shibari.photo" }`
  - Response includes a DNS target, e.g.:
    - `"cname": "example.herokudns.com"` or `"hostname": "example.shibari.photo"`.

### 4.4 Hetzner DNS API Usage

- **Base**
  - URL: `https://dns.hetzner.com/api/v1`
  - Headers:
    - `Auth-API-Token: <HETZNER_DNS_API_TOKEN>`

- **Find zone**
  - `GET /zones?name=shibari.photo`
  - Extract zone id from `zones[0].id`.

- **Create/update CNAME**
  - `POST /records`
    - Body:
      - `{ "zone_id": "<zone-id>", "name": "<name>", "type": "CNAME", "value": "<heroku_dns_target>", "ttl": 300 }`
  - To update:
    - `GET /records?zone_id=<zone-id>&name=<name>&type=CNAME`
    - If record exists and overwrite allowed:
      - `PUT /records/{id}` with updated `value`.

### 4.5 Error Handling Strategy

- Use small helper `raise_for_status_with_context` or inline checks to:
  - Log HTTP status codes and response bodies on failure.
  - Raise custom exceptions (`HerokuError`, `HetznerDNSError`) with clear messages.
- Phase-specific error messages:
  - “Heroku clone failed” vs “Config vars update failed” vs “Domain creation failed” vs “DNS record creation failed”.
- Exit codes:
  - `0` on success.
  - Non-zero on any uncaught error; message printed to stderr.

---

## 5. Data & Configuration

### CLI Arguments
- `--name`:
  - Used for:
    - Deriving Heroku app name (if `--heroku-app-name` is not provided).
    - Creating custom domain `<name>.shibari.photo`.
    - CNAME record name in Hetzner (`name` field).
- `--folder`:
  - Used to set `[Dropbox].image_folder` in `FETLIFE_INI`.

### Environment Variables
- `HEROKU_API_TOKEN`:
  - Heroku personal/API token with app/manage scope.
- `HETZNER_DNS_API_TOKEN`:
  - Hetzner DNS API token.

### Internal Data Structures
- Simple Python dicts for:
  - Config vars mapping `str -> str`.
  - API JSON payloads/responses.

---

## 6. Testing Strategy

### Unit Tests (where practical)
- Place tests under a new directory, e.g., `publisher_v2/tests/scripts/test_heroku_hetzner_clone.py`, focusing on:
  - `update_image_folder`:
    - Correctly updates `[Dropbox].image_folder` given a valid INI string.
    - Raises or fails clearly if `[Dropbox]` or `image_folder` is missing.
  - `HerokuClient` and `HetznerDNSClient`:
    - Use `responses` or simple stub classes to validate request construction (URLs, methods, payloads).
  - CLI argument parsing:
    - Validates required args and trims/normalizes input.

### Integration / Manual Validation
- Given this script interacts with external APIs, most end-to-end tests will be manual or behind environment flags:
  - Run against a staging Heroku app and a test Hetzner zone.
  - Verify:
    - App clone exists and is accessible via `heroku apps:info`.
    - Config vars are cloned and `FETLIFE_INI` has updated `[Dropbox].image_folder`.
    - Heroku domain `<name>.shibari.photo` is created and has a DNS target.
    - Hetzner DNS record for `<name>.shibari.photo` matches the Heroku DNS target.

---

## 7. Rollout & Migration

- Initial rollout:
  - Add the script to `/scripts` and document usage in a short README section (high-level only).
  - No changes to application runtime or config loaders; safe to merge independently.
- Migration:
  - Operators gradually shift from manual cloning to using the script.
  - No automated migration is required; the script is an additional tool.
- Rollback:
  - If issues arise, remove or stop using the script; no changes to the core application are needed.
  - Apps/DNS already created via the script can be managed manually in Heroku/Hetzner as before.

---

## 8. Success Criteria

- A new Heroku app can be provisioned from `fetlife-prod` using a single CLI command.
- The new app has:
  - All config vars from `fetlife-prod` (with `FETLIFE_INI` updated as requested).
  - A working custom domain `<name>.shibari.photo`.
- Hetzner DNS has a corresponding CNAME record pointing to the Heroku DNS target.
- The script is small, readable, and clearly separated from the main V2 runtime, with no regressions to existing behavior.

---

## 9. References

- Feature Request: `docs_v2/08_Features/08_01_Feature_Request/011_heroku-hetzner-app-cloning.md`  
- Heroku Platform API docs (apps, config-vars, domains).  
- Hetzner DNS API docs (zones, records).  


