<!-- docs_v2/08_Features/08_04_ChangeRequests/011/003_delete-server.md -->

# Story 003 — Delete Server by Name

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 003  
**Name:** delete-server  
**Status:** Proposed  
**Date:** 2025-11-21  
**Author:** Story Workflow  

## Summary

Add a delete flow to the `heroku_hetzner_clone.py` script so that an operator can delete a server (Heroku app + Hetzner DNS entry) and remove its entry from `scripts/servers.txt` by running the script with the server `name` as a parameter.  
This provides a symmetric cleanup path to complement the existing provisioning flow.

## Problem Statement

The current automation makes it easy to provision new Heroku apps with associated Hetzner DNS subdomains and logs them to `scripts/servers.txt`, but cleanup is entirely manual:

- Operators must delete the Heroku app via the Heroku dashboard or CLI.
- Remove the matching CNAME from Hetzner DNS.
- Manually edit `servers.txt` to remove the stale entry.

This is error-prone and makes it harder to keep environments tidy, especially when many short-lived or tenant-specific instances are created.

## Goals

- Allow operators to run a single command with a `name` parameter to:
  - Delete the corresponding Heroku app(s) for that name.
  - Remove the matching Hetzner DNS CNAME record(s) for `<name>.shibari.photo`.
  - Remove the corresponding line(s) from `scripts/servers.txt`.
- Provide a dry-run mode that clearly describes what would be deleted without performing any destructive actions.
- Keep the behavior localized to the `scripts` folder and avoid impacting the main V2 runtime.

## Non-Goals

- Implementing bulk or pattern-based deletions.
- Restoring deleted apps or DNS records.
- Changing how provisioning or logging works for new servers.

## Acceptance Criteria

- Given `scripts/servers.txt` contains an entry for `name=tati` with the corresponding Heroku URL and subdomain URL, when I run:

  ```bash
  python scripts/heroku_hetzner_clone.py --action delete --name tati
  ```

  then:
  - The Heroku app derived from the stored Heroku URL is deleted.
  - The Hetzner CNAME record for `tati` in the `shibari.photo` zone is deleted (if present).
  - All lines in `scripts/servers.txt` whose first field is `tati` are removed from the file.

- Given I run the same command with `--dry-run`, then:
  - No Heroku apps are deleted.
  - No Hetzner DNS records are deleted.
  - `scripts/servers.txt` is not modified.
  - The script prints a clear description of what *would* be deleted.

## Dependencies

- Feature 011 design: `docs_v2/08_Features/08_02_Feature_Design/011_heroku-hetzner-app-cloning_design.md`.  
- Logging story: `docs_v2/08_Features/08_04_ChangeRequests/011/001_servers-log_story.md`.  
- Provisioning script: `scripts/heroku_hetzner_clone.py`.  


