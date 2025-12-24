<!-- docs_v2/08_Epics/08_04_ChangeRequests/011/002_web-admin-password_story.md -->

# Story 002 — web-admin-password — Shipped

**Feature ID:** 011  
**Feature Name:** heroku-hetzner-app-cloning  
**Story ID:** 002  
**Name:** web-admin-password  
**Status:** Shipped  
**Date:** 2025-11-21  
**Author:** Story Workflow  

---

## Summary

This story extends the `heroku_hetzner_clone.py` provisioning script so that each newly created Heroku app has an explicit web admin password configured at creation time.  
It introduces a required CLI parameter `--password` and uses that value to set (or overwrite) the `web_admin_pw` config var on the new app, aligning with the existing web admin auth design that reads `web_admin_pw` from the environment.

---

## Implementation Overview

**Files touched**
- `scripts/heroku_hetzner_clone.py`
- Story docs under `docs_v2/08_Epics/08_04_ChangeRequests/011/002_*`

### CLI Changes

- Added a new **required** CLI argument:

  ```python
  parser.add_argument(
      "--password",
      required=True,
      help="Web admin password for the new app; sets the web_admin_pw config var.",
  )
  ```

- The help text clarifies that this password will be used to configure `web_admin_pw` on the new Heroku app.
- The existing `--dry-run` behavior is unchanged; operators still need to pass `--password` syntactically, but no config vars are written in dry-run mode.

### Config Vars Update

- In the existing config copy section, after cloning config vars from the source app and updating `FETLIFE_INI`, the script now:

  ```python
  new_cfg: Dict[str, str] = dict(source_cfg)
  new_cfg["FETLIFE_INI"] = updated_ini

  keep_existed = "FEATURE_KEEP_CURATE" in new_cfg
  remove_existed = "FEATURE_REMOVE_CURATE" in new_cfg
  new_cfg["FEATURE_KEEP_CURATE"] = "true"
  new_cfg["FEATURE_REMOVE_CURATE"] = "true"

  # Always set/overwrite web_admin_pw from the CLI password
  admin_pw_existed = "web_admin_pw" in new_cfg
  new_cfg["web_admin_pw"] = args.password

  heroku.set_config_vars(new_app_name, new_cfg)
  ```

- Logging was extended to reflect the action taken:

  ```python
  admin_action = "Set" if not admin_pw_existed else "Overwritten"
  _print(f"  -> {admin_action} web_admin_pw from --password")
  ```

- Result:
  - If the source app did **not** have `web_admin_pw`, the new app’s `web_admin_pw` is **set** from `--password`.
  - If the source app did have `web_admin_pw`, the new app’s value is **overwritten** with `--password`, ensuring the operator-selected password is always applied.

---

## Behavior

- **Non-dry-run**
  - Running:

    ```bash
    python scripts/heroku_hetzner_clone.py \
      --name tati \
      --folder /Photos/tati \
      --password s3cret \
      ...
    ```

    now:
    - Creates/couples the new app, updates config vars, sets feature flags, enables ACM, creates the custom domain, configures Hetzner DNS, and promotes from staging as before.
    - Ensures the new app has `web_admin_pw = "s3cret"` in its config vars.

- **Dry-run**
  - With `--dry-run`, the script returns early before any Heroku API calls, including `set_config_vars`; no `web_admin_pw` changes are made.
  - `--password` is still syntactically required by argparse, but its value is never used against Heroku.

---

## Alignment with Web Auth

- `publisher_v2/src/publisher_v2/web/auth.py` expects `web_admin_pw` in the environment to enable admin mode:

  ```python
  def get_admin_password() -> Optional[str]:
      return _get_env("web_admin_pw")
  ```

- By setting `web_admin_pw` during provisioning, each new instance created via the script is immediately capable of supporting web admin mode (subject to operators knowing the chosen password).

---

## Testing

- Existing automated tests for `heroku_hetzner_clone.py` (focused on `update_image_folder`) continue to pass.
- Manual validation is recommended:
  - After running the script with a test password, verify in the Heroku dashboard that the new app’s config vars include `web_admin_pw` with the expected value.

---

## Artifacts

- Change Request: `docs_v2/08_Epics/08_04_ChangeRequests/011/002_web-admin-password.md`  
- Design: `docs_v2/08_Epics/08_04_ChangeRequests/011/002_web-admin-password_design.md`  
- Plan: `docs_v2/08_Epics/08_04_ChangeRequests/011/002_web-admin-password_plan.yaml`  
- Shipped Story Doc: `docs_v2/08_Epics/08_04_ChangeRequests/011/002_web-admin-password_story.md`  


