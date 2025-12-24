<!-- docs_v2/08_Epics/08_04_ChangeRequests/011/001_servers-log_story.md -->

# Story 001 — servers-log — Shipped

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 001  
**Name:** servers-log  
**Status:** Shipped  
**Date:** 2025-11-21  
**Author:** Story Workflow  

---

## Summary

This story adds a simple, append-only `servers.txt` log file under the `scripts/` directory, updated by the `heroku_hetzner_clone.py` provisioning script.  
Each successful, non-dry-run provisioning run appends a line containing the logical instance name, Dropbox image folder, Heroku app URL, subdomain URL, and a UTC creation timestamp.  
The log file is ignored by Git so that local environment-specific server lists are never committed to the repository.

---

## Implementation Overview

**Files touched**
- `scripts/heroku_hetzner_clone.py`
- `.gitignore`

**Key changes**
- Added a helper function `append_server_record(...)` to `scripts/heroku_hetzner_clone.py`:
  - Accepts `name`, `folder`, `heroku_url`, and `subdomain_url`.
  - Computes `created_at` as `datetime.utcnow().isoformat(timespec="seconds") + "Z"`.
  - Appends a CSV-style line to `scripts/servers.txt`:
    - `name,folder,heroku_url,subdomain_url,created_at`.
  - Uses `Path(__file__).resolve().parent / "servers.txt"` to ensure the file lives in the `scripts/` directory.

- Integrated the helper into the main provisioning flow:
  - After all main steps complete successfully (app creation, pipeline coupling, config copy/update, ACM enablement, custom domain creation, Hetzner DNS CNAME, and pipeline promotion), `main()` now:
    - Calls `append_server_record(...)` with:
      - `name=args.name`
      - `folder=args.folder`
      - `heroku_url=web_url`
      - `subdomain_url=f"https://{hostname}"`
    - Wraps the call in a `try/except OSError` so that log write failures produce a warning but do not break a successful provisioning run.
  - Dry-run mode remains unchanged; it returns early and does not touch `servers.txt`.

- Updated `.gitignore`:
  - Added:
    - `scripts/servers.txt`
  - This ensures the log file is not tracked by Git and does not show up in `git status`.

---

## Behavior

- **On successful provisioning**  
  Running:

  ```bash
  python scripts/heroku_hetzner_clone.py \
    --name tati \
    --folder /Photos/tati
  ```

  now:
  - Completes the existing provisioning flow (Heroku app, pipeline, config vars, ACM, domain, Hetzner DNS, promotion).
  - Appends a line to `scripts/servers.txt` similar to:

    ```text
    tati,/Photos/tati,https://fetlife-prod-tati.herokuapp.com,https://tati.shibari.photo,2025-11-21T18:42:10Z
    ```

- **On dry-run**
  - When `--dry-run` is specified, the script exits before any external API calls or file writes.
  - `servers.txt` is not created or modified.

- **Git behavior**
  - `scripts/servers.txt` is now ignored:
    - It will not be committed.
    - It will not appear as an untracked or modified file in `git status`.

---

## Testing

- Existing unit tests for `update_image_folder` continue to pass (`publisher_v2/tests/test_scripts_heroku_hetzner_clone.py`).
- Logging behavior for `servers.txt` is intentionally simple and side-effectful; validation is expected to be manual:
  - Run the script in a test environment with valid credentials.
  - Confirm:
    - `scripts/servers.txt` appears/updates after a successful run.
    - Each run appends a new line.
    - Dry-run leaves the file untouched.

---

## Artifacts

- Change Request: `docs_v2/08_Epics/08_04_ChangeRequests/011/001_servers-log.md`  
- Design: `docs_v2/08_Epics/08_04_ChangeRequests/011/001_servers-log_design.md`  
- Plan: `docs_v2/08_Epics/08_04_ChangeRequests/011/001_servers-log_plan.yaml`  
- Shipped Story Doc: `docs_v2/08_Epics/08_04_ChangeRequests/011/001_servers-log_story.md`  


