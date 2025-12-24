<!-- docs_v2/08_Epics/08_04_ChangeRequests/011/003_delete-server_design.md -->

# Story 003 — delete-server — Design

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 003  
**Name:** delete-server  
**Status:** Design Review  
**Date:** 2025-11-21  
**Author:** Story Workflow  

---

## 1. Summary

This story adds a deletion capability to the `heroku_hetzner_clone.py` script that allows operators to clean up a previously provisioned server by its logical `name`.  
The delete flow:

- Looks up the server in `scripts/servers.txt` by name.
- Deletes the corresponding Heroku app(s).
- Deletes the matching Hetzner DNS CNAME record(s).
- Removes the server entry from `scripts/servers.txt`.

The behavior is invoked via a new CLI action flag and respects the existing dry-run semantics.

---

## 2. Context & Assumptions

### 2.1 Current State

- **Provisioning flow**:
  - `scripts/heroku_hetzner_clone.py` provisions a new Heroku app, configures domains, DNS, and promotions, and appends a record to `scripts/servers.txt` containing:

    ```text
    <name>,<folder>,<heroku_url>,<subdomain_url>,<created_at_utc>
    ```

- **DNS integration**:
  - Hetzner DNS CNAMEs are created under the `shibari.photo` zone via `HetznerDNSClient.ensure_cname(...)` with `name=<name>` and `value=<heroku_dns_target>.`.

- **Heroku integration**:
  - `HerokuClient` already supports:
    - Creating apps.
    - Managing config vars.
    - Creating domains (with `sni_endpoint`).
    - Adding apps to pipelines.
    - Promoting releases via pipelines.

### 2.2 Assumptions

1. Each logical instance is uniquely identified by its `name` (first field in `servers.txt` and the subdomain label).
2. Heroku URLs recorded in `servers.txt` follow the pattern:
   - `https://<app-name>.herokuapp.com` (with or without trailing `/`).
3. Deleting an app via Heroku API is sufficient to remove it from pipelines and associated domains; we do not need to manually detach pipeline couplings.

---

## 3. Design

### 3.1 CLI Interface

Extend the CLI with an `--action` flag:

```python
parser.add_argument(
    "--action",
    choices=["create", "delete"],
    default="create",
    help="Action to perform: 'create' a new app or 'delete' an existing one from servers.txt (default: create).",
)
```

Key behaviors:
- **Create mode (default)**:
  - The existing provisioning behavior remains unchanged.
  - `--folder`, `--password`, and other options behave as previously implemented.
- **Delete mode**:
  - Triggered by `--action delete`.
  - Requires `--name` (already mandatory).
  - Ignores other flags like `--folder`, `--password`, etc., beyond printing summary metadata where useful.

### 3.2 Helpers

#### 3.2.1 Parse Heroku app name from URL

Add a small helper to extract the app name from a Heroku URL:

```python
def _parse_app_name_from_heroku_url(heroku_url: str) -> Optional[str]:
    """
    Extract the Heroku app name from a standard Heroku URL.
    Expected formats:
      - https://<app-name>.herokuapp.com
      - https://<app-name>.herokuapp.com/
    """
    if not heroku_url:
        return None
    parsed = urlparse(heroku_url)
    host = parsed.netloc or parsed.path
    host = host.strip()
    if host.endswith("/"):
        host = host[:-1]
    suffix = ".herokuapp.com"
    if host.endswith(suffix):
        return host[: -len(suffix)]
    return None
```

#### 3.2.2 Delete flow helper

Add `_delete_server_by_name`:

```python
def _delete_server_by_name(
    args: argparse.Namespace,
    heroku: HerokuClient,
    hetzner: HetznerDNSClient,
) -> int:
    """
    Delete a server by name:
      - Remove matching records from scripts/servers.txt
      - Delete the corresponding Heroku app(s)
      - Delete the corresponding Hetzner DNS CNAME record(s)
    """
    path = Path(__file__).resolve().parent / "servers.txt"
    # ... read lines, collect matches, handle dry-run, perform deletions ...
```

Behavior details:

- **Read `servers.txt`**:
  - If the file does not exist or is empty → error and exit with non-zero status.
  - Parse lines as CSV:
    - `name,folder,heroku_url,subdomain_url,created_at`
    - Keep lines with malformed structure untouched in `remaining`.
  - Collect all entries where `record_name == args.name` into `to_delete`.
  - If `to_delete` is empty → error and exit non-zero.

- **Dry-run**:

  ```python
  if args.dry_run:
      for parts in to_delete:
          rec_name, folder, heroku_url, subdomain_url, *rest = parts + ["", "", "", ""]
          _print(
              f"  - Would delete Heroku app derived from {heroku_url} "
              f"and DNS record for {rec_name}.shibari.photo "
              f"(folder={folder}, subdomain_url={subdomain_url})"
          )
      return 0
  ```

- **Delete Heroku apps**:
  - For each `parts` in `to_delete`:
    - Extract `app_name = _parse_app_name_from_heroku_url(heroku_url)`.
    - If `app_name` is resolved:

      ```python
      heroku.delete_app(app_name)
      ```

    - If parsing fails, log a warning and skip app deletion for that record.

- **Delete Hetzner DNS CNAMEs**:
  - Resolve zone:

    ```python
    zone = hetzner.get_zone_by_name("shibari.photo")
    zone_id = zone["id"]
    ```

  - For each `rec_name` in `to_delete`:
    - Lookup CNAME record:

      ```python
      record = hetzner.find_record(zone_id=zone_id, name=rec_name, rtype="CNAME")
      ```

    - If found, call `hetzner.delete_record(record["id"])`.
    - If not found, log a “nothing to delete” message.

- **Rewrite `servers.txt`**:
  - After attempting deletions, rewrite the file with `remaining` entries.
  - If `remaining` is non-empty, write them joined by newlines plus a trailing newline.
  - If empty, truncate the file to empty.

### 3.3 Client Extensions

Extend `HerokuClient`:

```python
def delete_app(self, app_name: str) -> None:
    """Delete a Heroku app by name."""
    url = f"{HEROKU_API_BASE}/apps/{app_name}"
    resp = self.session.delete(url, timeout=30)
    if resp.status_code >= 400:
        raise HerokuError(
            f"Failed to delete Heroku app '{app_name}': "
            f"{resp.status_code} {resp.text}"
        )
```

Extend `HetznerDNSClient`:

```python
def delete_record(self, record_id: str) -> None:
    """Delete a DNS record by id."""
    url = f"{HETZNER_API_BASE}/records/{record_id}"
    resp = self.session.delete(url, timeout=30)
    if resp.status_code >= 400:
        raise HetznerDNSError(
            f"Failed to delete DNS record '{record_id}': "
            f"{resp.status_code} {resp.text}"
        )
```

### 3.4 Main Flow Integration

In `main()`:

- After parsing args and instantiating clients, branch on `args.action`:

```python
if args.action == "delete":
    try:
        return _delete_server_by_name(args, heroku, hetzner)
    except (HerokuError, HetznerDNSError, ValueError, configparser.Error) as exc:
        sys.stderr.write(f"\nerror: {exc}\n")
        return 1
```

- The existing create flow remains unchanged and runs when `args.action == "create"` (default).

---

## 4. Error Handling

- Missing `servers.txt` or no matches for `name`:
  - The script prints a clear error and exits with status `1`.
- Failed Heroku app deletion:
  - Logs a warning and continues attempting DNS deletion and file rewrite.
- Failed DNS deletion:
  - Logs a warning and continues; the `servers.txt` entry is still removed, reflecting operator intent.
- Dry-run:
  - Never calls delete APIs or mutates `servers.txt`.

---

## 5. Testing Strategy

- Automated tests:
  - Existing tests for `update_image_folder` remain green.
  - We intentionally avoid adding brittle tests that depend on external Heroku/Hetzner behavior for deletion.

- Manual tests:
  - Provision a test instance, confirm `servers.txt` has an entry for a given `name`.
  - Run:

    ```bash
    python scripts/heroku_hetzner_clone.py --action delete --name testname --dry-run
    ```

    and verify only descriptive output is printed.

  - Run without `--dry-run` and confirm:
    - The Heroku app is deleted.
    - The Hetzner CNAME record is removed.
    - The corresponding line(s) are removed from `scripts/servers.txt`.

---

## 6. Success Criteria

- Operators can reliably delete a server by `name` using a single CLI command.
- Heroku apps and Hetzner DNS records for that name are cleaned up.
- `scripts/servers.txt` no longer contains entries for the deleted name.
- Dry-run clearly communicates intended actions without side effects.


