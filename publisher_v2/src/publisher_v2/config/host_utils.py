from __future__ import annotations

import re


_RE_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_RE_HAS_PORT_SUFFIX = re.compile(r":\d+$")
_RE_PLAUSIBLE_IPV6 = re.compile(r"^[0-9a-f:]+$", re.IGNORECASE)


def normalize_host(host: str) -> str:
    """
    Normalize a host per orchestrator contract:
    - lowercase
    - strip :port
    - strip trailing dot
    - reject leading/trailing whitespace (caller should validate)
    """
    h = host.lower()
    # Strip trailing dot first (so ":443." becomes ":443"), then strip port.
    h = h.rstrip(".")
    h = _RE_HAS_PORT_SUFFIX.sub("", h)
    h = h.rstrip(".")
    return h


def validate_host(host: str) -> bool:
    """
    Return False for invalid host shapes. These should be rejected without calling
    the orchestrator (privacy-preserving 404 behavior).
    """
    if host is None:
        return False

    # Reject leading/trailing whitespace or empty
    if not host or host != host.strip():
        return False

    h = normalize_host(host.strip())
    if not h:
        return False

    # Reject obvious invalid label shapes
    if h.startswith(".") or h.endswith(".") or ".." in h:
        return False

    # Reject localhost and www.*
    if h == "localhost" or h.startswith("www."):
        return False

    # Reject IPv4 literals (note: does not validate octet ranges; good enough for shape rejection)
    if _RE_IPV4.match(h):
        return False

    # Reject IPv6 literals and bracketed IPv6
    if h.startswith("[") and h.endswith("]"):
        return False
    if "::" in h:
        return False
    if _RE_PLAUSIBLE_IPV6.match(h) and ":" in h:
        return False

    return True


def extract_tenant(host: str, base_domain: str) -> str:
    """
    Extract tenant label from <tenant>.<base_domain>.
    If host does not end with base_domain, returns first label.
    """
    h = normalize_host(host.strip())
    bd = base_domain.strip().lower().lstrip(".").rstrip(".")
    if bd and h.endswith("." + bd):
        remainder = h[: -len(bd) - 1]
        return remainder.split(".", 1)[0]
    return h.split(".", 1)[0]


