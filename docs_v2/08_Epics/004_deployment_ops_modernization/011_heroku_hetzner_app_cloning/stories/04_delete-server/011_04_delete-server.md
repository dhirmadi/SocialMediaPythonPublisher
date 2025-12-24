<!-- docs_v2/08_Epics/08_04_ChangeRequests/011/003_delete-server_story.md -->

# Story 003 — delete-server — Shipped

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 003  
**Name:** delete-server  
**Status:** Shipped  
**Date:** 2025-11-21  
**Author:** Story Workflow  

---

## Summary

This story adds a delete flow to the `heroku_hetzner_clone.py` script that allows operators to remove a server by its logical `name`.  
The delete action:
- Reads `scripts/servers.txt` to find matching entries for the given `name`.
- Deletes the associated Heroku app(s).
- Deletes the corresponding Hetzner DNS CNAME record(s) for `<name>.shibari.photo`.
- Removes the matching lines from `scripts/servers.txt`.

It also supports a dry-run mode to preview the deletions without making changes.

---

## Implementation Overview

**Files touched**
- `scripts/heroku_hetzner_clone.py`
- Story docs under `docs_v2/08_Epics/08_04_ChangeRequests/011/003_*`

### CLI: New `--action` Flag

- Extended the CLI with:

  ```python
  parser.add_argument(
      "--action",
      choices=["create", "delete"],
      default="create",
      help="Action to perform: 'create' a new app or 'delete' an existing one from servers.txt (default: create).",
  )
  ```

- The script now prints a small summary including the action and name.
- **Create** remains the default, so existing provisioning usage is unchanged.
- **Delete** is invoked via `--action delete --name <name>`.

### Helpers

- Added `append_server_record(...)` earlier (Story 001) — unchanged.

- New helper to parse app name from a Heroku URL:

  ```python
  def _parse_app_name_from_heroku_url(heroku_url: str) -> Optional[str]:
      """
      Extract the Heroku app name from a standard Heroku URL:
        - https://<app-name>.herokuapp.com[/]
      """
      # Uses urllib.parse.urlparse and strips '.herokuapp.com'
  ```

- New delete flow helper:

  ```python
  def _delete_server_by_name(
      args: argparse.Namespace,
      heroku: HerokuClient,
      hetzner: HetznerDNSClient,
  ) -> int:
      # Reads scripts/servers.txt, finds matching lines by name,
      # performs dry-run or real deletions, rewrites servers.txt.
  ```

### Client Extensions

- **HerokuClient** now includes:

  ```python
  def delete_app(self, app_name: str) -> None:
      url = f"{HEROKU_API_BASE}/apps/{app_name}"
      resp = self.session.delete(url, timeout=30)
      if resp.status_code >= 400:
          raise HerokuError(...)
  ```

- **HetznerDNSClient** now includes:

  ```python
  def delete_record(self, record_id: str) -> None:
      url = f"{HETZNER_API_BASE}/records/{record_id}"
      resp = self.session.delete(url, timeout=30)
      if resp.status_code >= 400:
          raise HetznerDNSError(...)
  ```

### Main Flow Integration

- In `main()`, after constructing clients:

  ```python
  if args.action == "delete":
      try:
          return _delete_server_by_name(args, heroku, hetzner)
      except (HerokuError, HetznerDNSError, ValueError, configparser.Error) as exc:
          sys.stderr.write(f"\nerror: {exc}\n")
          return 1
  ```

- The existing provisioning flow remains the default when `args.action == "create"`.

### Delete Behavior

- **Lookup**
  - Reads `scripts/servers.txt` from the `scripts/` directory.
  - Collects all lines whose first field (before the first comma) matches `--name`.
  - If no matches:
    - Prints a clear error and exits non-zero.

- **Dry-run**
  - With `--dry-run`, the script:
    - Prints, for each matching record, a message like:

      > Would delete Heroku app derived from `<heroku_url>` and DNS record for `<name>.shibari.photo` (folder=`<folder>`, subdomain_url=`<subdomain_url>`)

    - Returns without deleting apps, DNS records, or modifying `servers.txt`.

- **Real deletion**
  - Resolves the Hetzner zone `shibari.photo` once.
  - For each matching record:
    - Derives the app name from the stored `heroku_url` via `_parse_app_name_from_heroku_url` and, if successful, calls `heroku.delete_app(app_name)`.
    - Looks up a CNAME record in Hetzner DNS for `name=<rec_name>` and, if present, calls `hetzner.delete_record(record["id"])`.
    - Logs warnings if deletions fail but continues with other records.
  - Rewrites `scripts/servers.txt` with remaining lines only; if no remaining entries exist, truncates the file to empty.

---

## Usage Examples

- **Dry-run delete**:

  ```bash
  python scripts/heroku_hetzner_clone.py --action delete --name tati --dry-run
  ```

- **Real delete**:

  ```bash
  python scripts/heroku_hetzner_clone.py --action delete --name tati
  ```

After a successful delete:
- The Heroku app(s) matched by `tati` in `servers.txt` will be gone.
- The Hetzner CNAME for `tati.shibari.photo` will be removed (if present).
- All `tati` lines will be removed from `scripts/servers.txt`.

---

## Testing

- Existing unit tests for the script (focused on `update_image_folder`) continue to pass.
- Delete behavior is validated via manual tests in a non-production Heroku/Hetzner environment.

---

## Artifacts

- Change Request: `docs_v2/08_Epics/08_04_ChangeRequests/011/003_delete-server.md`  
- Design: `docs_v2/08_Epics/08_04_ChangeRequests/011/003_delete-server_design.md`  
- Plan: `docs_v2/08_Epics/08_04_ChangeRequests/011/003_delete-server_plan.yaml`  
- Shipped Story Doc: `docs_v2/08_Epics/08_04_ChangeRequests/011/003_delete-server_story.md`  


