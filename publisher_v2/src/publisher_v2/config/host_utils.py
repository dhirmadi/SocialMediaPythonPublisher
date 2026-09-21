"""Host normalization and validation shared by the config sources and web layer.

Hosts are the tenant routing key, so these helpers are deliberately strict: the orchestrator
is only queried for host shapes that pass :func:`validate_host`, which keeps bogus lookups
from leaking tenant existence.
"""

import re

_RE_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_RE_HAS_PORT_SUFFIX = re.compile(r":\d+$")
_RE_PLAUSIBLE_IPV6 = re.compile(r"^[0-9a-f:]+$", re.IGNORECASE)


def normalize_host(host: str) -> str:
    """Normalize a host to the form the orchestrator keys tenants by.

    Per orchestrator contract:
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
    """Report whether a host shape is worth sending to the orchestrator.

    Returns False for invalid host shapes. These should be rejected without calling
    the orchestrator (privacy-preserving 404 behavior). Rejected: empty or untrimmed
    input, empty/dotted-edge labels, ``localhost``, ``www.*``, and IPv4/IPv6 literals.
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
    return not (_RE_PLAUSIBLE_IPV6.match(h) and ":" in h)


def extract_tenant(host: str, base_domain: str) -> str:
    """Guess a tenant label from a host — NOT AUTHORITATIVE, see below.

    NOT AUTHORITATIVE (#89): for hosts outside the base domain this returns
    the first DNS label, which collapses distinct custom-domain tenants.
    Use only for standalone host validation — credential resolution must use
    the orchestrator's runtime.tenant.


    Extract tenant label from <tenant>.<base_domain>.
    If host does not end with base_domain, returns first label.
    """
    h = normalize_host(host.strip())
    bd = base_domain.strip().lower().lstrip(".").rstrip(".")
    if bd and h.endswith("." + bd):
        remainder = h[: -len(bd) - 1]
        return remainder.split(".", 1)[0]
    return h.split(".", 1)[0]
