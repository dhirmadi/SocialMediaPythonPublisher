<!-- docs_v2/08_Epics/08_04_ChangeRequests/011/001_servers-log_design.md -->

# Story 001 — servers-log — Design

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 001  
**Name:** servers-log  
**Status:** Design Review  
**Date:** 2025-11-21  
**Author:** Story Workflow  

---

## 1. Summary

This story extends the Heroku/Hetzner provisioning script by adding a small, append-only `servers.txt` log file under the `scripts/` directory.  
Each successful, non-dry-run execution of `scripts/heroku_hetzner_clone.py` that completes the full provisioning flow will append a single line capturing:

- `name` — CLI `--name` argument (subdomain/app instance identifier).
- `folder` — CLI `--folder` argument (Dropbox image folder path).
- `heroku_url` — the base URL for the new Heroku app.
- `subdomain_url` — the HTTPS URL for the new subdomain (`https://<name>.shibari.photo`).
- `created_at` — UTC timestamp in ISO 8601-like format.

The file is for local/operator use only and will be ignored by Git.

---

## 2. Scope & Non-Goals

**In scope**
- Adding a small helper in `scripts/heroku_hetzner_clone.py` to append lines to `servers.txt`.
- Calling this helper at the end of a successful provisioning run (after domain + DNS + promotion).
- Ensuring `servers.txt` is added to `.gitignore`.

**Out of scope**
- Changing any behavior of the provisioning flow itself (app creation, config vars, DNS, promotion).
- Building query/management tools around `servers.txt`.
- Backfilling historic entries for existing apps.

---

## 3. Design Details

### 3.1 File Location & Format

- **Path:** `scripts/servers.txt` (relative to repository root; script resolves it using `__file__`).
- **Format:** One record per line, comma-separated values:

  ```text
  <name>,<folder>,<heroku_url>,<subdomain_url>,<created_at>
  ```

  Example:

  ```text
  tati,/Photos/tati,https://fetlife-prod-tati.herokuapp.com,https://tati.shibari.photo,2025-11-21T18:42:10Z
  ```

- **Encoding:** UTF-8.
- **Header:** None; purely append-only data lines.

### 3.2 Helper Function

Add a small helper function near the top of `scripts/heroku_hetzner_clone.py`:

```python
from pathlib import Path
from datetime import datetime


def append_server_record(
    name: str,
    folder: str,
    heroku_url: str,
    subdomain_url: str,
) -> None:
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    line = f"{name},{folder},{heroku_url},{subdomain_url},{ts}\n"
    path = Path(__file__).resolve().parent / "servers.txt"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
```

Behavior:
- Creates `servers.txt` if it doesn’t exist.
- Appends a new line for each call.
- Does not attempt to de-duplicate or rewrite existing lines.

### 3.3 Integration into Main Flow

In `main()`, **only after** all provisioning steps succeed (app created, pipeline-coupled, config updated, ACM enabled, domain + DNS created, pipeline promotion triggered) and **before** returning `0`, call `append_server_record`:

```python
append_server_record(
    name=args.name,
    folder=args.folder,
    heroku_url=web_url,
    subdomain_url=f"https://{hostname}",
)
```

Wrap this in a small `try/except OSError` block so that logging failures do not break an otherwise successful provisioning:

```python
try:
    append_server_record(...)
    _print("Server record appended to scripts/servers.txt")
except OSError as log_exc:
    sys.stderr.write(f"\nwarning: failed to write servers.txt: {log_exc}\n")
```

**Dry-run behavior**
- The call to `append_server_record` is inside the normal (non-dry-run) path; the existing early return for `--dry-run` means no file is written in dry-run mode.

### 3.4 Git Ignore

Update root `.gitignore` to include:

```text
scripts/servers.txt
```

This ensures:
- `servers.txt` does not show up in `git status`.
- Local server lists created by different operators or CI jobs do not conflict.

---

## 4. Error Handling & Safety

- **File write failures**
  - If writing to `servers.txt` fails (e.g., permissions, read-only FS), the script:
    - Prints a warning to stderr.
    - Still exits with `0` if all provisioning steps succeeded.
- **Partial failures earlier in the flow**
  - The helper is only called after success; if any earlier step raises, `servers.txt` is not touched.
- **Dry-run**
  - Dry-run exits early and never logs or mutates `servers.txt`.

---

## 5. Testing Strategy

Given that `servers.txt` is a side-effectful, environment-specific file in `/scripts`, and the existing test suite only validates `update_image_folder`, we will:

- Keep automated tests focused on stable, pure logic (no new tests required for `servers.txt`).
- Validate `servers.txt` behavior via manual checks:
  - Run the script in a test environment with a valid Heroku/Hetzner setup.
  - Confirm that:
    - `scripts/servers.txt` is created/updated after a successful run.
    - Each run appends a new line.
    - Dry-run mode leaves the file untouched.

---

## 6. Alignment with Feature 011

This story is strictly additive to feature 011:
- It does not impact how apps are cloned, configured, or promoted.
- It does not affect Hetzner DNS behavior beyond reusing the computed URLs.
- It respects the repo rule that secrets and config stay out of committed files; `servers.txt` is ignored.

---

## 7. Success Criteria

- After a successful provisioning run, `scripts/servers.txt` contains a new line with the expected five fields.
- `git status` remains clean with respect to `servers.txt`.
- Dry-run executions do not modify or create `servers.txt`.


