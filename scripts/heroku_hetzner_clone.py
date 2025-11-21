#!/usr/bin/env python3
"""
Heroku + Hetzner DNS automation script for Social Media Publisher.

This tool clones a reference Heroku app (default: fetlife-prod), updates the
FETLIFE_INI config var's [Dropbox].image_folder for the new app, attaches a
custom domain <name>.shibari.photo, and configures a matching CNAME record
in Hetzner DNS.
"""

from __future__ import annotations

import argparse
import configparser
import io
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


HEROKU_API_BASE = "https://api.heroku.com"
HETZNER_API_BASE = "https://dns.hetzner.com/api/v1"


class HerokuError(RuntimeError):
    """Errors raised when interacting with the Heroku Platform API."""


class HetznerDNSError(RuntimeError):
    """Errors raised when interacting with the Hetzner DNS API."""


def _print(msg: str) -> None:
    """Print helper to keep output formatting consistent."""
    sys.stdout.write(msg + "\n")


# Load environment variables from a .env file in the current working
# directory or its parents. This allows operators to keep HEROKU_API_TOKEN
# and HETZNER_DNS_API_TOKEN in .env instead of exporting them explicitly.
load_dotenv()


def append_server_record(
    name: str,
    folder: str,
    heroku_url: str,
    subdomain_url: str,
) -> None:
    """
    Append a single server record line to scripts/servers.txt.

    Format:
      <name>,<folder>,<heroku_url>,<subdomain_url>,<created_at_utc>
    """
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    line = f"{name},{folder},{heroku_url},{subdomain_url},{ts}\n"
    path = Path(__file__).resolve().parent / "servers.txt"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


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
    if not path.exists():
        sys.stderr.write("error: scripts/servers.txt not found; nothing to delete.\n")
        return 1

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        sys.stderr.write("error: scripts/servers.txt is empty; nothing to delete.\n")
        return 1

    name = args.name
    to_delete: list[list[str]] = []
    remaining: list[str] = []

    for line in lines:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 4:
            # Malformed line; keep it but do not try to act on it.
            remaining.append(line)
            continue
        rec_name = parts[0]
        if rec_name == name:
            to_delete.append(parts)
        else:
            remaining.append(line)

    if not to_delete:
        sys.stderr.write(
            f"error: no server entry with name '{name}' found in scripts/servers.txt\n"
        )
        return 1

    _print(
        f"\n[delete] Found {len(to_delete)} server record(s) for name '{name}' in scripts/servers.txt"
    )

    if args.dry_run:
        for parts in to_delete:
            rec_name, folder, heroku_url, subdomain_url, *rest = parts + ["", "", "", ""]
            _print(
                f"  - Would delete Heroku app derived from {heroku_url} "
                f"and DNS record for {rec_name}.shibari.photo "
                f"(folder={folder}, subdomain_url={subdomain_url})"
            )
        return 0

    # Real deletion: delete Heroku app(s) and Hetzner DNS record(s), then rewrite servers.txt.
    zone = hetzner.get_zone_by_name("shibari.photo")
    zone_id = zone["id"]

    for parts in to_delete:
        rec_name, folder, heroku_url, subdomain_url, *rest = parts + ["", "", "", ""]
        # Derive the Heroku app name from the logical instance name using the
        # same pattern as creation (fetlife-prod-<name>), instead of relying
        # on the stored URL which may include older naming schemes.
        app_name = normalize_heroku_app_name(rec_name)

        _print(f"  - Deleting Heroku app '{app_name}'...")
        try:
            heroku.delete_app(app_name)
            _print("    -> Heroku app deleted.")
        except HerokuError as exc:
            sys.stderr.write(f"\nwarning: failed to delete Heroku app '{app_name}': {exc}\n")

        _print(f"  - Deleting Hetzner DNS CNAME for '{rec_name}.shibari.photo'...")
        try:
            record = hetzner.find_record(zone_id=zone_id, name=rec_name, rtype="CNAME")
            if record:
                hetzner.delete_record(record["id"])
                _print("    -> DNS record deleted.")
            else:
                _print("    -> No matching DNS record found; nothing to delete.")
        except HetznerDNSError as exc:
            sys.stderr.write(
                f"\nwarning: failed to delete DNS record for '{rec_name}.shibari.photo': {exc}\n"
            )

    # Rewrite servers.txt with remaining records only.
    # Preserve a trailing newline if there are remaining entries.
    if remaining:
        path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    else:
        # If no remaining records, truncate the file to empty.
        path.write_text("", encoding="utf-8")

    _print(f"\nRemoved {len(to_delete)} record(s) for name '{name}' from scripts/servers.txt")
    return 0


def normalize_heroku_app_name(name: str) -> str:
    """
    Derive a Heroku app name for a logical instance name using the fixed
    pattern: fetlife-prod-<name>.

    Heroku app names:
    - Must be lowercase.
    - Can contain letters, numbers, and dashes.
    - Must start with a letter.
    """
    base = f"fetlife-prod-{name}"
    base = base.lower()
    base = re.sub(r"[^a-z0-9-]+", "-", base)
    base = re.sub(r"-{2,}", "-", base).strip("-")
    if not base or not base[0].isalpha():
        base = f"a-{base}" if base else "a-instance"
    return base[:30]


def validate_subdomain_label(label: str) -> None:
    """
    Validate that a subdomain label is DNS-safe.

    Accepts:
    - a–z, A–Z, 0–9, and '-'
    - must not start or end with '-'
    """
    if not label:
        raise ValueError("Subdomain name must not be empty.")
    if not re.fullmatch(r"[A-Za-z0-9-]+", label):
        raise ValueError(
            f"Invalid subdomain name '{label}': only letters, numbers, and '-' are allowed."
        )
    if label[0] == "-" or label[-1] == "-":
        raise ValueError(f"Invalid subdomain name '{label}': cannot start or end with '-'.")


def update_image_folder(ini_text: str, new_folder: str) -> str:
    """
    Update the [Dropbox].image_folder value in an INI string.

    Raises ValueError if the [Dropbox] section or image_folder key is missing
    or if the result cannot be parsed back into a valid INI.
    """
    if not new_folder:
        raise ValueError("New image_folder value must not be empty.")

    parser = configparser.ConfigParser()
    parser.read_string(ini_text)

    if "Dropbox" not in parser:
        raise ValueError("FETLIFE_INI is missing required [Dropbox] section.")
    if "image_folder" not in parser["Dropbox"]:
        raise ValueError("FETLIFE_INI [Dropbox] section is missing image_folder key.")

    parser["Dropbox"]["image_folder"] = new_folder

    buf = io.StringIO()
    parser.write(buf)
    updated = buf.getvalue()

    # Validate round-trip parse
    check = configparser.ConfigParser()
    check.read_string(updated)
    if "Dropbox" not in check or "image_folder" not in check["Dropbox"]:
        raise ValueError("Updated FETLIFE_INI is invalid after modification.")

    return updated


@dataclass
class HerokuClient:
    api_token: str
    session: requests.Session

    @classmethod
    def from_env(cls) -> "HerokuClient":
        token = os.environ.get("HEROKU_API_TOKEN")
        if not token:
            raise HerokuError("HEROKU_API_TOKEN environment variable is required.")
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.heroku+json; version=3",
                "Content-Type": "application/json",
            }
        )
        return cls(api_token=token, session=session)

    def get_app(self, app_name: str) -> Dict[str, Any]:
        """Fetch metadata for a Heroku app."""
        url = f"{HEROKU_API_BASE}/apps/{app_name}"
        resp = self.session.get(url, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to fetch app '{app_name}': {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_pipeline_by_name(self, pipeline_name: str) -> Dict[str, Any]:
        """Get pipeline info by name."""
        url = f"{HEROKU_API_BASE}/pipelines"
        resp = self.session.get(url, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to list pipelines: {resp.status_code} {resp.text}"
            )
        pipelines = resp.json()
        for pipeline in pipelines:
            if pipeline.get("name") == pipeline_name:
                return pipeline
        raise HerokuError(f"Pipeline '{pipeline_name}' not found.")

    def create_app(self, new_name: str) -> Dict[str, Any]:
        """Create a new blank Heroku app."""
        url = f"{HEROKU_API_BASE}/apps"
        resp = self.session.post(url, json={"name": new_name}, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to create Heroku app '{new_name}': "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()

    def add_app_to_pipeline(self, app_id: str, pipeline_id: str, stage: str = "production") -> Dict[str, Any]:
        """Add an app to a pipeline at a specific stage."""
        url = f"{HEROKU_API_BASE}/pipeline-couplings"
        payload = {
            "app": app_id,
            "pipeline": pipeline_id,
            "stage": stage
        }
        resp = self.session.post(url, json=payload, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to add app to pipeline: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def enable_acm(self, app_name: str) -> Dict[str, Any]:
        """Enable Automated Certificate Management (ACM) for an app."""
        url = f"{HEROKU_API_BASE}/apps/{app_name}/acm"
        resp = self.session.post(url, json={}, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to enable ACM for app '{app_name}': "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()

    def promote_release(
        self,
        source_app: str,
        target_app: str,
        pipeline_id: str,
    ) -> Dict[str, Any]:
        """
        Promote the current release (slug) from source_app to target_app
        using the Heroku pipelines promotion API.
        """
        source_info = self.get_app(source_app)
        target_info = self.get_app(target_app)

        url = f"{HEROKU_API_BASE}/pipeline-promotions"
        # Per Heroku docs, promotion payload must include:
        # - pipeline: { id }
        # - source: { app: { id } }
        # - targets: [ { app: { id } } ]
        payload = {
            "pipeline": {"id": pipeline_id},
            "source": {"app": {"id": source_info.get("id")}},
            "targets": [{"app": {"id": target_info.get("id")}}],
        }
        # Promotions use the pipeline-promotion media type.
        headers = {
            "Accept": "application/vnd.heroku+json; version=3.pipeline-promotion",
        }
        resp = self.session.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to promote from '{source_app}' to '{target_app}': "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_config_vars(self, app_name: str) -> Dict[str, str]:
        url = f"{HEROKU_API_BASE}/apps/{app_name}/config-vars"
        resp = self.session.get(url, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to fetch config vars for app '{app_name}': "
                f"{resp.status_code} {resp.text}"
            )
        # Heroku returns a JSON object mapping names to values.
        return resp.json()

    def set_config_vars(self, app_name: str, config: Dict[str, str]) -> None:
        url = f"{HEROKU_API_BASE}/apps/{app_name}/config-vars"
        resp = self.session.patch(url, json=config, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to set config vars for app '{app_name}': "
                f"{resp.status_code} {resp.text}"
            )

    def get_sni_endpoints(self, app_name: str) -> list[Dict[str, Any]]:
        """Get all SNI endpoints for an app (for ACM SSL certificates)."""
        url = f"{HEROKU_API_BASE}/apps/{app_name}/sni-endpoints"
        resp = self.session.get(url, timeout=30)
        if resp.status_code >= 400:
            # SNI endpoints might not exist yet, return empty list
            return []
        return resp.json()

    def create_domain(self, app_name: str, hostname: str) -> Dict[str, Any]:
        """
        Create a custom domain for the app.

        As of November 2021, the Heroku Domains API requires the
        `sni_endpoint` parameter. For apps with Automated Certificate
        Management (ACM) enabled, this can be explicitly set to null
        to let Heroku manage the SNI endpoint automatically.
        """
        url = f"{HEROKU_API_BASE}/apps/{app_name}/domains"

        # Per Heroku changelog, always include sni_endpoint; for ACM-managed
        # apps this should be null.
        payload = {"hostname": hostname, "sni_endpoint": None}
        resp = self.session.post(url, json=payload, timeout=30)

        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to create domain '{hostname}' for app '{app_name}': "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()

    def delete_app(self, app_name: str) -> None:
        """Delete a Heroku app by name."""
        url = f"{HEROKU_API_BASE}/apps/{app_name}"
        resp = self.session.delete(url, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to delete Heroku app '{app_name}': "
                f"{resp.status_code} {resp.text}"
            )


@dataclass
class HetznerDNSClient:
    api_token: str
    session: requests.Session

    @classmethod
    def from_env(cls) -> "HetznerDNSClient":
        token = os.environ.get("HETZNER_DNS_API_TOKEN")
        if not token:
            raise HetznerDNSError("HETZNER_DNS_API_TOKEN environment variable is required.")
        session = requests.Session()
        session.headers.update(
            {
                "Auth-API-Token": token,
                "Content-Type": "application/json",
            }
        )
        return cls(api_token=token, session=session)

    def get_zone_by_name(self, name: str) -> Dict[str, Any]:
        url = f"{HETZNER_API_BASE}/zones"
        resp = self.session.get(url, params={"name": name}, timeout=30)
        if resp.status_code >= 400:
            raise HetznerDNSError(
                f"Failed to list Hetzner DNS zones for '{name}': "
                f"{resp.status_code} {resp.text}"
            )
        data = resp.json()
        zones = data.get("zones") or []
        if not zones:
            raise HetznerDNSError(f"No Hetzner DNS zone found for '{name}'.")
        return zones[0]

    def find_record(
        self, *, zone_id: str, name: str, rtype: str = "CNAME"
    ) -> Optional[Dict[str, Any]]:
        url = f"{HETZNER_API_BASE}/records"
        resp = self.session.get(
            url, params={"zone_id": zone_id, "name": name, "type": rtype}, timeout=30
        )
        if resp.status_code >= 400:
            raise HetznerDNSError(
                f"Failed to list DNS records for zone '{zone_id}': "
                f"{resp.status_code} {resp.text}"
            )
        data = resp.json()
        records = data.get("records") or []
        return records[0] if records else None

    def create_record(
        self, *, zone_id: str, name: str, target: str, ttl: int = 300
    ) -> Dict[str, Any]:
        url = f"{HETZNER_API_BASE}/records"
        payload = {
            "value": target,
            "type": "CNAME",
            "name": name,
            "zone_id": zone_id,
            "ttl": ttl,
        }
        resp = self.session.post(url, json=payload, timeout=30)
        if resp.status_code >= 400:
            raise HetznerDNSError(
                f"Failed to create CNAME record '{name}' in zone '{zone_id}': "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()

    def update_record(self, record_id: str, *, name: str, target: str, ttl: int = 300) -> Dict[str, Any]:
        url = f"{HETZNER_API_BASE}/records/{record_id}"
        payload = {
            "value": target,
            "type": "CNAME",
            "name": name,
            "ttl": ttl,
        }
        resp = self.session.put(url, json=payload, timeout=30)
        if resp.status_code >= 400:
            raise HetznerDNSError(
                f"Failed to update CNAME record '{record_id}' ('{name}'): "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()

    def ensure_cname(
        self, *, zone_id: str, name: str, target: str, overwrite: bool = True
    ) -> Dict[str, Any]:
        existing = self.find_record(zone_id=zone_id, name=name, rtype="CNAME")
        if existing:
            if not overwrite:
                return existing
            record_id = existing["id"]
            return self.update_record(record_id, name=name, target=target)
        return self.create_record(zone_id=zone_id, name=name, target=target)

    def delete_record(self, record_id: str) -> None:
        """Delete a DNS record by id."""
        url = f"{HETZNER_API_BASE}/records/{record_id}"
        resp = self.session.delete(url, timeout=30)
        if resp.status_code >= 400:
            raise HetznerDNSError(
                f"Failed to delete DNS record '{record_id}': "
                f"{resp.status_code} {resp.text}"
            )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clone a Heroku app (default fetlife-prod), update FETLIFE_INI image_folder, "
            "attach a <name>.shibari.photo domain, and configure Hetzner DNS."
        )
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Instance name used for the subdomain (<name>.shibari.photo) and derived Heroku app name.",
    )
    parser.add_argument(
        "--folder",
        required=False,
        help="New [Dropbox].image_folder value to inject into the FETLIFE_INI config var.",
    )
    parser.add_argument(
        "--heroku-source-app",
        default="fetlife-prod",
        help="Source Heroku app to clone from (default: fetlife-prod).",
    )
    parser.add_argument(
        "--heroku-app-name",
        default=None,
        help="Explicit name for the new Heroku app (otherwise derived from source app and --name).",
    )
    parser.add_argument(
        "--password",
        required=False,
        help="Web admin password for the new app; sets the web_admin_pw config var.",
    )
    parser.add_argument(
        "--heroku-staging-app",
        default="fetlife",
        help="Staging Heroku app to promote code from via pipelines (default: fetlife).",
    )
    parser.add_argument(
        "--action",
        choices=["create", "delete"],
        default="create",
        help="Action to perform: 'create' a new app or 'delete' an existing one from servers.txt (default: create).",
    )
    parser.add_argument(
        "--pipeline",
        default="fetlife",
        help="Heroku pipeline name to add the new app to (default: fetlife).",
    )
    parser.add_argument(
        "--pipeline-stage",
        default="production",
        choices=["development", "staging", "production"],
        help="Pipeline stage for the new app (default: production).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned operations without calling external APIs.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    try:
        validate_subdomain_label(args.name)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    # Enforce required parameters for create (non-dry-run) at runtime so that
    # delete flows can omit them.
    if args.action == "create" and not args.dry_run:
        missing: list[str] = []
        if not args.folder:
            missing.append("--folder")
        if not args.password:
            missing.append("--password")
        if missing:
            sys.stderr.write(
                f"error: {', '.join(missing)} required when action=create (non-dry-run)\n"
            )
            return 1

    new_app_name = args.heroku_app_name or normalize_heroku_app_name(args.name)
    hostname = f"{args.name}.shibari.photo"

    _print("=== Heroku + Hetzner automation ===")
    _print(f"- Action:           {args.action}")
    _print(f"- Name:             {args.name}")
    if args.action == "create":
        _print(f"- Source app:       {args.heroku_source_app}")
        _print(f"- Staging app:      {args.heroku_staging_app}")
        _print(f"- New app name:     {new_app_name}")
        _print(f"- Pipeline:         {args.pipeline} ({args.pipeline_stage})")
        _print(f"- Subdomain:        {hostname}")
        _print(f"- image_folder:     {args.folder}")
        _print(f"- Dry run:          {args.dry_run}")
    else:
        _print(f"- Subdomain:        {hostname}")
        _print(f"- Dry run:          {args.dry_run}")

    if args.dry_run:
        _print("\nDry-run mode enabled; no external API calls will be made.")
        return 0

    try:
        heroku = HerokuClient.from_env()
        hetzner = HetznerDNSClient.from_env()
    except (HerokuError, HetznerDNSError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    # Delete flow: clean up Heroku + Hetzner DNS and update servers.txt
    if args.action == "delete":
        try:
            return _delete_server_by_name(args, heroku, hetzner)
        except (HerokuError, HetznerDNSError, ValueError, configparser.Error) as exc:
            sys.stderr.write(f"\nerror: {exc}\n")
            return 1

    # Create flow: default behavior
    try:
        _print("\n[1/7] Creating new Heroku app...")
        app_info = heroku.create_app(new_app_name)
        app_id = app_info.get("id")
        web_url = app_info.get("web_url") or f"https://{new_app_name}.herokuapp.com"
        _print(f"  -> New app created: {app_info.get('name', new_app_name)}")
        _print(f"  -> App ID: {app_id}")
        _print(f"  -> Web URL: {web_url}")

        _print(f"\n[1b/7] Adding app to '{args.pipeline}' pipeline...")
        pipeline = heroku.get_pipeline_by_name(args.pipeline)
        pipeline_id = pipeline.get("id")
        coupling = heroku.add_app_to_pipeline(app_id, pipeline_id, args.pipeline_stage)
        _print(f"  -> Added to pipeline '{args.pipeline}' at stage '{args.pipeline_stage}'")

        _print("\n[2/7] Copying and updating config vars from source app...")
        source_cfg = heroku.get_config_vars(args.heroku_source_app)
        ini_text = source_cfg.get("FETLIFE_INI")
        if ini_text is None:
            raise HerokuError(
                "Source app is missing FETLIFE_INI config var; cannot update image_folder."
            )
        updated_ini = update_image_folder(ini_text, args.folder)
        
        # Build new config: copy source vars exactly, update FETLIFE_INI, ensure feature flags
        new_cfg: Dict[str, str] = dict(source_cfg)
        new_cfg["FETLIFE_INI"] = updated_ini

        # Always set/overwrite feature flags and related env vars
        keep_existed = "FEATURE_KEEP_CURATE" in new_cfg
        remove_existed = "FEATURE_REMOVE_CURATE" in new_cfg
        analyze_existed = "FEATURE_ANALYZE_CAPTION" in new_cfg
        publish_existed = "FEATURE_PUBLISH" in new_cfg
        new_cfg["FEATURE_KEEP_CURATE"] = "true"
        new_cfg["FEATURE_REMOVE_CURATE"] = "true"
        new_cfg["FEATURE_ANALYZE_CAPTION"] = "false"
        new_cfg["FEATURE_PUBLISH"] = "false"
        # Always set/overwrite AUTO_VIEW to false on new servers
        auto_view_existed = "AUTO_VIEW" in new_cfg
        new_cfg["AUTO_VIEW"] = "false"
        # Always set/overwrite web_admin_pw from the CLI password
        admin_pw_existed = "web_admin_pw" in new_cfg
        new_cfg["web_admin_pw"] = args.password

        heroku.set_config_vars(new_app_name, new_cfg)
        _print(f"  -> Copied {len(source_cfg)} config vars from {args.heroku_source_app}")
        _print("  -> Updated FETLIFE_INI [Dropbox].image_folder")

        keep_action = "Set" if not keep_existed else "Overwritten"
        remove_action = "Set" if not remove_existed else "Overwritten"
        _print(f"  -> {keep_action} FEATURE_KEEP_CURATE=true")
        _print(f"  -> {remove_action} FEATURE_REMOVE_CURATE=true")
        analyze_action = "Set" if not analyze_existed else "Overwritten"
        publish_action = "Set" if not publish_existed else "Overwritten"
        _print(f"  -> {analyze_action} FEATURE_ANALYZE_CAPTION=false")
        _print(f"  -> {publish_action} FEATURE_PUBLISH=false")
        auto_view_action = "Set" if not auto_view_existed else "Overwritten"
        _print(f"  -> {auto_view_action} AUTO_VIEW=false")
        admin_action = "Set" if not admin_pw_existed else "Overwritten"
        _print(f"  -> {admin_action} web_admin_pw from --password")

        _print("\n[3/7] Enabling Automated Certificate Management (ACM)...")
        acm_info = heroku.enable_acm(new_app_name)
        _print(f"  -> ACM enabled for {new_app_name}")

        _print("\n[4/7] Creating Heroku custom domain...")
        domain = heroku.create_domain(new_app_name, hostname)
        dns_target = (
            domain.get("cname")
            or domain.get("dns_target")
            or domain.get("hostname")
        )
        if not dns_target:
            raise HerokuError(
                f"Heroku domain response did not include a DNS target: {domain!r}"
            )
        # For DNS zone files and Hetzner records, use a fully-qualified
        # domain name with a trailing dot to avoid relative expansions.
        if not dns_target.endswith("."):
            dns_target_dns = dns_target + "."
        else:
            dns_target_dns = dns_target

        _print(f"  -> Domain created: {hostname}")
        _print(f"  -> DNS target:     {dns_target_dns}")

        _print("\n[5/7] Configuring Hetzner DNS CNAME...")
        zone = hetzner.get_zone_by_name("shibari.photo")
        zone_id = zone["id"]
        record = hetzner.ensure_cname(
            zone_id=zone_id,
            name=args.name,
            target=dns_target_dns,
        )
        _print(
            f"  -> CNAME record ensured in zone {zone['name']} "
            f"(name={record.get('name')}, value={record.get('value')})"
        )

        _print("\n[6/7] Promoting code from staging app via pipeline...")
        promotion = heroku.promote_release(
            args.heroku_staging_app,
            new_app_name,
            pipeline_id,
        )
        promotion_id = promotion.get("id")
        _print(
            f"  -> Promotion triggered from '{args.heroku_staging_app}' "
            f"to '{new_app_name}' (promotion id={promotion_id})"
        )

        _print("\n[7/7] Summary")
        _print(f"New app:        {new_app_name}")
        _print(f"Heroku URL:     {web_url}")
        _print(f"Custom domain:  https://{hostname}")
        _print(
            f"Code source:    Promoted from staging app '{args.heroku_staging_app}' "
            f"via pipelines"
        )
        _print(f"\nOnce promotion completes, the app will be live at https://{hostname}")

        # Best-effort append to scripts/servers.txt; do not fail the run if this
        # logging step encounters an OS error.
        try:
            append_server_record(
                name=args.name,
                folder=args.folder,
                heroku_url=web_url,
                subdomain_url=f"https://{hostname}",
            )
            _print("Server record appended to scripts/servers.txt")
        except OSError as log_exc:
            sys.stderr.write(f"\nwarning: failed to write servers.txt: {log_exc}\n")

        return 0
    except (HerokuError, HetznerDNSError, ValueError, configparser.Error) as exc:
        sys.stderr.write(f"\nerror: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())


