from __future__ import annotations

import pytest

from publisher_v2.config.host_utils import normalize_host, validate_host, extract_tenant


def test_normalize_host_lowercase_strips_port_and_dot() -> None:
    assert normalize_host("TeNaNt.Shibari.Photo:8080.") == "tenant.shibari.photo"


@pytest.mark.parametrize(
    "host",
    [
        "",
        "   ",
        " tenant.shibari.photo",
        "tenant.shibari.photo ",
        "localhost",
        "www.tenant.shibari.photo",
        "tenant..shibari.photo",
        "127.0.0.1",
        "[::1]",
        "::1",
        "dead:beef",
    ],
)
def test_validate_host_rejects_invalid_shapes(host: str) -> None:
    assert validate_host(host) is False


@pytest.mark.parametrize(
    "host",
    [
        "tenant.shibari.photo",
        "tenant.shibari.photo:443",
        "foo.bar.shibari.photo",
    ],
)
def test_validate_host_accepts_reasonable_hosts(host: str) -> None:
    assert validate_host(host) is True


def test_extract_tenant_from_base_domain() -> None:
    assert extract_tenant("xxx.shibari.photo", "shibari.photo") == "xxx"
    assert extract_tenant("xxx.shibari.photo:443", "shibari.photo") == "xxx"


def test_extract_tenant_fallback_first_label() -> None:
    assert extract_tenant("a.b.example.com", "shibari.photo") == "a"


