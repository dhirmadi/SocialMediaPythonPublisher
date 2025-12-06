<!-- docs_v2/08_Features/08_04_ChangeRequests/011/002_web-admin-password_design.md -->

# Story 002 — web-admin-password — Design

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 002  
**Name:** web-admin-password  
**Status:** Design Review  
**Date:** 2025-11-21  
**Author:** Story Workflow  

---

## 1. Summary

This story tightens the provisioning workflow for new Heroku instances created by `scripts/heroku_hetzner_clone.py` by:

- Adding a **mandatory** CLI parameter `--password` representing the web admin password for the new instance.
- Ensuring the cloned app’s config vars always include `web_admin_pw` set to the provided password.

This aligns the provisioning automation with the existing web admin auth design, which expects `web_admin_pw` to be configured in the environment in order to enable admin mode.

---

## 2. Context & Constraints

### 2.1 Existing Behavior

- **Parent feature (011)**:
  - `heroku_hetzner_clone.py`:
    - Creates a new Heroku app derived from `fetlife-prod`.
    - Copies config vars from the source app and updates `FETLIFE_INI` `[Dropbox].image_folder`.
    - Ensures feature flags like `FEATURE_KEEP_CURATE` / `FEATURE_REMOVE_CURATE` are set to `"true"`.
    - Configures a custom domain `<name>.shibari.photo` and Hetzner DNS CNAME.
    - Promotes a slug from a staging app via pipelines.
    - Logs a record to `scripts/servers.txt`.

- **Web admin auth** (`publisher_v2/src/publisher_v2/web/auth.py`):
  - `get_admin_password()`:

    ```python
    def get_admin_password() -> Optional[str]:
        """
        Read the admin password from environment (web_admin_pw).
        """
        # Intentionally lower-case to match .env naming in the change request.
        return _get_env("web_admin_pw")
    ```

  - If `web_admin_pw` is not set or empty, admin mode is considered unavailable.

### 2.2 Requirements from Story

- CLI must expose a **required** parameter `--password`:
  - Used to set `web_admin_pw` in the new app’s config vars.
  - Required for non-dry-run executions; optional (or any value) in `--dry-run` where no config is actually written.
- When cloning config vars:
  - Always set or overwrite `web_admin_pw` on the **new** app using the value provided via `--password` (i.e., the CLI wins over any inherited value).

### 2.3 Constraints & Considerations

- **Security**
  - Passing a password via CLI inevitably exposes it in shell history unless operators mitigate (e.g., shell history ignore, wrapping scripts).
  - The story explicitly calls for a CLI parameter; we document this trade-off but keep scope minimal.
- **Backwards compatibility**
  - Existing usage of the script without `--password` will now fail fast; this is acceptable since the script is new and used by a small set of operators.
  - Dry-run behavior must remain side-effect-free; we will not create or update config vars in dry-run mode.

---

## 3. Detailed Design

### 3.1 CLI Changes

In `scripts/heroku_hetzner_clone.py`, extend `parse_args`:

```python
parser.add_argument(
    "--password",
    required=True,
    help="Web admin password for the new app; sets the web_admin_pw config var.",
)
```

Notes:
- `required=True` ensures that non-dry-run executions must provide a password.
- The existing `--dry-run` early-return remains, so in practice:
  - For strict argparse semantics, `--password` is still syntactically required even in dry-run mode.
  - Operators can pass a placeholder in dry-run (e.g., `--password dummy`) with no side effects.

### 3.2 Config Var Update Logic

Current logic (simplified) when copying config vars:

```python
source_cfg = heroku.get_config_vars(args.heroku_source_app)
ini_text = source_cfg.get("FETLIFE_INI")
updated_ini = update_image_folder(ini_text, args.folder)

new_cfg: Dict[str, str] = dict(source_cfg)
new_cfg["FETLIFE_INI"] = updated_ini

keep_existed = "FEATURE_KEEP_CURATE" in new_cfg
remove_existed = "FEATURE_REMOVE_CURATE" in new_cfg
new_cfg["FEATURE_KEEP_CURATE"] = "true"
new_cfg["FEATURE_REMOVE_CURATE"] = "true"

heroku.set_config_vars(new_app_name, new_cfg)
```

Proposed extension:

```python
new_cfg: Dict[str, str] = dict(source_cfg)
new_cfg["FETLIFE_INI"] = updated_ini

# Always set/overwrite these feature flags to true (existing behavior)
keep_existed = "FEATURE_KEEP_CURATE" in new_cfg
remove_existed = "FEATURE_REMOVE_CURATE" in new_cfg
new_cfg["FEATURE_KEEP_CURATE"] = "true"
new_cfg["FEATURE_REMOVE_CURATE"] = "true"

# Always set/overwrite web_admin_pw from the CLI password
admin_pw_existed = "web_admin_pw" in new_cfg
new_cfg["web_admin_pw"] = args.password
```

- After `heroku.set_config_vars(new_app_name, new_cfg)`:
  - The new app will have `web_admin_pw` populated with the CLI password.
  - Any value inherited from the source app is intentionally overridden.

Logging additions:

```python
admin_action = "Set" if not admin_pw_existed else "Overwritten"
_print(f"  -> {admin_action} web_admin_pw from --password")
```

### 3.3 Dry-Run Semantics

- The existing code path:

```python
if args.dry_run:
    _print("\nDry-run mode enabled; no external API calls will be made.")
    return 0
```

remains unchanged and happens **before** any calls to `HerokuClient` or `HetznerDNSClient`, so:
- No config vars (including `web_admin_pw`) are ever written in dry-run.
- Operators must still supply `--password` syntactically, but it is never used against Heroku.

### 3.4 Error Handling

- If `--password` is missing in non-dry-run mode:
  - `argparse` will exit with a usage error before any code runs.
- If `set_config_vars` fails for any reason (including `web_admin_pw` issues):
  - The existing `HerokuError` handling path remains unchanged; it will print a clear error and exit.

---

## 4. Testing Strategy

Given this story only touches a script under `scripts/` and the core tests for feature 011 already cover `update_image_folder`, we keep automated testing minimal and focus on manual validation:

- **Manual tests (recommended)**
  - Run the script with a test Heroku environment:

    ```bash
    python scripts/heroku_hetzner_clone.py \
      --name testpw \
      --folder /Photos/testpw \
      --password s3cret-pw
    ```

    - Verify on the new Heroku app:
      - `web_admin_pw` config var exists and equals `s3cret-pw`.
  - Configure `web_admin_pw` on the source app and rerun with a different `--password`:
    - Confirm the new app uses the CLI value, not the inherited one.

- **Dry-run sanity check**
  - Run with `--dry-run` and `--password dummy`:
    - Confirm no new app or config updates occur.

Automated tests for the script remain focused on the pure `update_image_folder` helper; we avoid brittle tests that depend on Heroku-side behavior.

---

## 5. Alignment with Repo Rules

- **Security**
  - Password is stored only in Heroku config vars; not written to disk or logs beyond brief CLI invocation.
  - We do not log the actual password value.
- **Simplicity**
  - Change is localized to `scripts/heroku_hetzner_clone.py`.
  - No impact on the main V2 application or config schema.
- **Backward compatibility**
  - Script is new and primarily used by operators; tightening CLI requirements is acceptable and intentional.

---

## 6. Success Criteria

- Script refuses to run in non-dry-run mode without `--password`.
- New apps created by the script always have `web_admin_pw` set to the CLI-provided value.
- Dry-run mode remains non-destructive and does not touch config vars.


