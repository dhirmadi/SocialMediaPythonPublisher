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
from typing import Any, Dict, Optional

import requests


HEROKU_API_BASE = "https://api.heroku.com"
HETZNER_API_BASE = "https://dns.hetzner.com/api/v1"


class HerokuError(RuntimeError):
    """Errors raised when interacting with the Heroku Platform API."""


class HetznerDNSError(RuntimeError):
    """Errors raised when interacting with the Hetzner DNS API."""


def _print(msg: str) -> None:
    """Print helper to keep output formatting consistent."""
    sys.stdout.write(msg + "\n")


def normalize_heroku_app_name(source_app: str, name: str) -> str:
    """
    Derive a Heroku app name from a source app and logical instance name.

    Heroku app names:
    - Must be lowercase.
    - Can contain letters, numbers, and dashes.
    - Must start with a letter.
    """
    base = f"{source_app}-{name}"
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

    def fork_app(self, source_app: str, new_name: str) -> Dict[str, Any]:
        url = f"{HEROKU_API_BASE}/apps/{source_app}/actions/fork"
        resp = self.session.post(url, json={"name": new_name}, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to fork Heroku app '{source_app}' as '{new_name}': "
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

    def create_domain(self, app_name: str, hostname: str) -> Dict[str, Any]:
        url = f"{HEROKU_API_BASE}/apps/{app_name}/domains"
        resp = self.session.post(url, json={"hostname": hostname}, timeout=30)
        if resp.status_code >= 400:
            raise HerokuError(
                f"Failed to create domain '{hostname}' for app '{app_name}': "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()


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
        required=True,
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

    new_app_name = args.heroku_app_name or normalize_heroku_app_name(
        args.heroku_source_app, args.name
    )
    hostname = f"{args.name}.shibari.photo"

    _print("=== Heroku + Hetzner automation ===")
    _print(f"- Source app:       {args.heroku_source_app}")
    _print(f"- New app name:     {new_app_name}")
    _print(f"- Subdomain:        {hostname}")
    _print(f"- image_folder:     {args.folder}")
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

    try:
        _print("\n[1/4] Cloning Heroku app...")
        fork_info = heroku.fork_app(args.heroku_source_app, new_app_name)
        web_url = fork_info.get("web_url") or f"https://{new_app_name}.herokuapp.com"
        _print(f"  -> New app created: {fork_info.get('name', new_app_name)}")
        _print(f"  -> Web URL (best-effort): {web_url}")

        _print("\n[2/4] Cloning and updating config vars (FETLIFE_INI)...")
        source_cfg = heroku.get_config_vars(args.heroku_source_app)
        ini_text = source_cfg.get("FETLIFE_INI")
        if ini_text is None:
            raise HerokuError(
                "Source app is missing FETLIFE_INI config var; cannot update image_folder."
            )
        updated_ini = update_image_folder(ini_text, args.folder)
        new_cfg: Dict[str, str] = dict(source_cfg)
        new_cfg["FETLIFE_INI"] = updated_ini
        heroku.set_config_vars(new_app_name, new_cfg)
        _print("  -> Config vars cloned and FETLIFE_INI updated.")

        _print("\n[3/4] Creating Heroku custom domain...")
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
        _print(f"  -> Domain created: {hostname}")
        _print(f"  -> DNS target:     {dns_target}")

        _print("\n[4/4] Configuring Hetzner DNS CNAME...")
        zone = hetzner.get_zone_by_name("shibari.photo")
        zone_id = zone["id"]
        record = hetzner.ensure_cname(zone_id=zone_id, name=args.name, target=dns_target)
        _print(
            f"  -> CNAME record ensured in zone {zone['name']} "
            f"(name={record.get('name')}, value={record.get('value')})"
        )

        _print("\n=== Done ===")
        _print(f"New app:        {new_app_name}")
        _print(f"Heroku URL:     {web_url}")
        _print(f"Custom domain:  https://{hostname}")
        return 0
    except (HerokuError, HetznerDNSError, ValueError, configparser.Error) as exc:
        sys.stderr.write(f"\nerror: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())


