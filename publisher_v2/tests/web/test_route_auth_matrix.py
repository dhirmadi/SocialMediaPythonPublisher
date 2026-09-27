"""PUB-084 AC9 (#298): one route-auth inventory, checked against the running app, run over the auth matrix.

The inventory names routes by method and path template only — never by source line, which
went stale the first time the file moved (the old ids were ``<module>.py:<line>``).

Every admin route is driven through the real ``publisher_v2.web.app.app`` and the real
``require_auth``/``require_admin``; nothing in the auth path is patched. The request service is
a stub so each route can reach a 200 once auth lets it through: its storage is the real
``ManagedStorage`` over the shared ``FakeS3`` (tests/web/conftest.py), and the AI/publish work
is stubbed on the service.

This replaces three partial inventories: the PUB-048 AC2 strict-mode walk (12 routes, keyed by
stale source lines), #137's ``_MUTATING`` list (5 image routes, no library routes), and the
library router's own 401/403 checks.
"""

from __future__ import annotations

import ast
import base64
import inspect
import io
import re
import textwrap
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from publisher_v2.config.schema import ContentConfig, FeaturesConfig, ManagedStorageConfig, StoragePathConfig
from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value
from publisher_v2.web.models import AnalysisResponse, CurationResponse, ImageResponse, PublishResponse

from .conftest import MANAGED_KEY_PREFIX, FakeS3

WEB_TESTS = Path(__file__).resolve().parent
TESTS_ROOT = WEB_TESTS.parent

# Where the guard sits relative to the handler's own work:
#   auth_first  - ``await require_auth`` then ``require_admin`` in the handler body
#   admin_first - ``require_admin`` then ``await require_auth`` (voice profile, PUB-048 AC1)
#   view        - the ``verify_view_permissions`` dependency (admin only when auto-view is off)
AUTH_FIRST = "auth_first"
ADMIN_FIRST = "admin_first"
VIEW = "view"


@dataclass(frozen=True)
class AdminRoute:
    method: str
    path: str
    guard: str
    shaping: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def url(self) -> str:
        return self.path.replace("{filename}", "img.jpg")


ADMIN_ROUTES: tuple[AdminRoute, ...] = (
    AdminRoute("GET", "/api/images/list", VIEW),
    AdminRoute("GET", "/api/images/random", VIEW),
    AdminRoute("GET", "/api/images/{filename}", VIEW),
    AdminRoute("GET", "/api/images/{filename}/thumbnail", VIEW),
    AdminRoute("POST", "/api/images/{filename}/analyze", AUTH_FIRST),
    AdminRoute("POST", "/api/images/{filename}/publish", AUTH_FIRST),
    AdminRoute("POST", "/api/images/{filename}/keep", AUTH_FIRST),
    AdminRoute("POST", "/api/images/{filename}/remove", AUTH_FIRST),
    AdminRoute("POST", "/api/images/{filename}/delete", AUTH_FIRST),
    AdminRoute("GET", "/api/config/voice-profile", ADMIN_FIRST),
    AdminRoute("POST", "/api/config/voice-profile", ADMIN_FIRST, {"json": {"voice_profile": ["a line."]}}),
    AdminRoute("GET", "/api/library/objects", AUTH_FIRST),
    AdminRoute("POST", "/api/library/upload", AUTH_FIRST, {"upload": True}),
    AdminRoute("DELETE", "/api/library/objects/{filename}", AUTH_FIRST),
    AdminRoute("POST", "/api/library/objects/{filename}/move", AUTH_FIRST, {"json": {"target_folder": "keep"}}),
)


# --- deriving the admin routes from the running app ---------------------------------------------


def _resolve(node: ast.expr, namespace: dict[str, Any]) -> Any:
    """The object a call's ``func`` expression names, looked up in the function's own globals."""
    if isinstance(node, ast.Name):
        return namespace.get(node.id)
    if isinstance(node, ast.Attribute):
        owner = _resolve(node.value, namespace)
        return getattr(owner, node.attr, None) if owner is not None else None
    return None


def _reaches_require_admin(fn: Any, seen: set[int]) -> bool:
    """True when ``fn`` calls ``require_admin``, directly or through a ``publisher_v2.web`` helper."""
    from publisher_v2.web.auth import require_admin

    fn = inspect.unwrap(fn)
    if fn is require_admin:
        return True
    if id(fn) in seen or not inspect.isfunction(fn):
        return False
    seen.add(id(fn))
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _resolve(node.func, fn.__globals__)
        if target is require_admin:
            return True
        if (
            inspect.isfunction(target)
            and (target.__module__ or "").startswith("publisher_v2.web")
            and _reaches_require_admin(target, seen)
        ):
            return True
    return False


def _dependency_calls(dependant: Any) -> list[Any]:
    calls: list[Any] = []
    for dep in dependant.dependencies:
        if dep.call is not None:
            calls.append(dep.call)
        calls.extend(_dependency_calls(dep))
    return calls


def _api_routes(routes: Any) -> list[APIRoute]:
    """Every APIRoute, descending into included routers.

    FastAPI 0.14x keeps ``include_router`` results as a wrapper holding the original
    router (``original_router``); older versions copied the routes in flat. Both work.
    """
    out: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            out.append(route)
        elif getattr(route, "original_router", None) is not None:
            out.extend(_api_routes(route.original_router.routes))
    return out


def derived_admin_routes() -> set[tuple[str, str]]:
    """(method, path) of every route of the running app whose handler or dependencies reach ``require_admin``."""
    from publisher_v2.web.app import app

    found: set[tuple[str, str]] = set()
    for route in _api_routes(app.routes):
        callables = [route.endpoint, *_dependency_calls(route.dependant)]
        if any(_reaches_require_admin(fn, set()) for fn in callables):
            for method in route.methods or ():
                if method != "HEAD":
                    found.add((method, route.path))
    return found


# Mutating routes that are deliberately NOT admin-guarded. Every other POST/PUT/PATCH/DELETE route
# of the running app must reach ``require_admin`` (and so be in ADMIN_ROUTES) — a new mutating route
# is admin by default and has to be argued onto this list, not silently left open.
NON_ADMIN_MUTATING_ROUTES: dict[tuple[str, str], str] = {
    # #91 SEC-8: logout must work for anyone holding a cookie, including an expired or cross-tenant
    # one; it only revokes the presented sid and clears the cookie/session. POST under /api, so the
    # CSRF middleware covers it.
    ("POST", "/api/auth/logout"): "logout: revokes the presented cookie, CSRF-covered",
    # Deprecated alias of /api/auth/logout, kept for older clients; same handler body.
    ("POST", "/api/admin/logout"): "deprecated logout alias, CSRF-covered",
}
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def running_app_mutating_routes() -> tuple[set[tuple[str, str]], list[str]]:
    """(method, path) of every mutating route of the running app, plus routes the walk cannot inspect.

    Walks every route object, not only ``APIRoute``: a plain Starlette ``Route`` added with
    ``app.add_route`` still has ``methods``. A route with neither ``methods`` nor an included
    router (a ``Mount``ed sub-app, say) could hide mutating endpoints, so it is reported.
    """
    from publisher_v2.web.app import app

    found: set[tuple[str, str]] = set()
    uninspectable: list[str] = []

    def _walk(routes: Any) -> None:
        for route in routes:
            if getattr(route, "original_router", None) is not None:
                _walk(route.original_router.routes)
            elif getattr(route, "methods", None):
                found.update((m, route.path) for m in route.methods if m in MUTATING_METHODS)
            else:
                uninspectable.append(f"{type(route).__name__} {getattr(route, 'path', '?')}")

    _walk(app.routes)
    return found, uninspectable


def test_every_mutating_route_is_admin_or_allowlisted() -> None:
    """AC9: no mutating route of the running app escapes both the admin inventory and the explicit allowlist."""
    mutating, uninspectable = running_app_mutating_routes()
    admin = {(r.method, r.path) for r in ADMIN_ROUTES}

    assert ("POST", "/api/auth/logout") in mutating, "walk found no known mutating route"
    assert not uninspectable, f"routes the mutating-route walk cannot inspect: {uninspectable}"
    unguarded = sorted(mutating - admin - NON_ADMIN_MUTATING_ROUTES.keys())
    assert not unguarded, (
        f"mutating routes neither admin-guarded nor on NON_ADMIN_MUTATING_ROUTES: {unguarded} — "
        "guard them with require_admin (and add them to ADMIN_ROUTES) or allowlist them with a reason"
    )
    stale = sorted(NON_ADMIN_MUTATING_ROUTES.keys() - mutating)
    assert not stale, f"NON_ADMIN_MUTATING_ROUTES entries the running app does not serve: {stale}"
    both = sorted(NON_ADMIN_MUTATING_ROUTES.keys() & admin)
    assert not both, f"routes both admin-guarded and allowlisted as non-admin: {both}"


_SOURCE_LINE_REF = re.compile(r"""\b[\w/]+\.py:\d+\b""")


def test_route_inventory_covers_every_admin_route() -> None:
    """AC9: the inventory equals the running app's admin routes (library included), with no line numbers."""
    derived = derived_admin_routes()
    inventory = {(r.method, r.path) for r in ADMIN_ROUTES}

    assert any(path.startswith("/api/library/") for _m, path in derived), "derivation found no library route"
    missing = sorted(derived - inventory)
    stale = sorted(inventory - derived)
    assert not missing, f"admin routes missing from the inventory: {missing}"
    assert not stale, f"inventory entries that are not admin routes of the running app: {stale}"
    assert len(ADMIN_ROUTES) == len(inventory), "duplicate inventory entries"

    offenders: list[str] = []
    for path in sorted([*WEB_TESTS.rglob("test_*.py"), *(TESTS_ROOT / "web_integration").rglob("test_*.py")]):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _SOURCE_LINE_REF.search(line):
                offenders.append(f"{path.relative_to(TESTS_ROOT)}:{lineno}")
    assert not offenders, "route-auth tests must not name routes by source line: " + ", ".join(offenders)


# --- the auth matrix -------------------------------------------------------------------------------

TOKEN = "matrix-token"  # pragma: allowlist secret
BEARER = {"Authorization": f"Bearer {TOKEN}"}
BASIC_USER, BASIC_PASS = "matrix-user", "matrix-pass"  # pragma: allowlist secret
BASIC_ENV = {"WEB_AUTH_USER": BASIC_USER, "WEB_AUTH_PASS": BASIC_PASS}
BASIC = {"Authorization": "Basic " + base64.b64encode(f"{BASIC_USER}:{BASIC_PASS}".encode()).decode()}
WRONG_BEARER = {"Authorization": "Bearer not-the-matrix-token"}
AUTH0 = {"AUTH0_DOMAIN": "test.auth0.com", "AUTH0_CLIENT_ID": "cid", "AUTH0_CLIENT_SECRET": "csecret"}
TENANT_HOST = "tenant-a.shibari.photo"

STRICT = "Header authentication required in addition to the admin cookie"
NOT_ADMIN = "Admin privileges required"
ADMIN_UNCONFIGURED = "Admin mode not configured"
VIEW_ADMIN_UNCONFIGURED = "Image viewing requires admin mode but admin is not configured"
TENANT_DISABLED = "Admin mode disabled for this tenant"


@dataclass(frozen=True)
class Scenario:
    """One row of the auth matrix: the dyno's configuration and what the caller presents."""

    name: str
    env: dict[str, str]
    cookie: bool
    headers: dict[str, str]
    # guard -> (status, detail); ``None`` detail means the route's own 200 body.
    expect: dict[str, tuple[int, str | None]]
    orchestrated_tenant_without_auth0: bool = False


SCENARIOS: tuple[Scenario, ...] = (
    # PUB-048 AC2 (#187): strict mode, a stolen cookie alone gets nowhere — on every admin route.
    Scenario(
        "strict mode, cookie only",
        {"WEB_AUTH_TOKEN": TOKEN, "WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE": "1", **AUTH0},
        cookie=True,
        headers={},
        expect={AUTH_FIRST: (401, STRICT), ADMIN_FIRST: (401, STRICT), VIEW: (401, STRICT)},
    ),
    # PUB-048 AC2 regression guard: a valid header plus a valid cookie still gets in everywhere.
    Scenario(
        "strict mode, header and cookie",
        {"WEB_AUTH_TOKEN": TOKEN, "WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE": "1", **AUTH0},
        cookie=True,
        headers=BEARER,
        expect={AUTH_FIRST: (200, None), ADMIN_FIRST: (200, None), VIEW: (200, None)},
    ),
    # PUB-048 AC2: Basic auth is a header backend too — Basic plus a valid cookie gets in everywhere.
    Scenario(
        "strict mode, Basic header and cookie",
        {**BASIC_ENV, "WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE": "1", **AUTH0},
        cookie=True,
        headers=BASIC,
        expect={AUTH_FIRST: (200, None), ADMIN_FIRST: (200, None), VIEW: (200, None)},
    ),
    # PUB-048 AC1: the header is re-verified, not merely present. require_auth rejects a presented
    # header that does not verify (401 "Unauthorized") before require_admin runs; where
    # require_admin runs first (voice profile, view), the cookie passes and its strict-mode
    # re-verification answers.
    Scenario(
        "strict mode, invalid header and cookie",
        {"WEB_AUTH_TOKEN": TOKEN, "WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE": "1", **AUTH0},
        cookie=True,
        headers=WRONG_BEARER,
        expect={AUTH_FIRST: (401, "Unauthorized"), ADMIN_FIRST: (401, STRICT), VIEW: (401, STRICT)},
    ),
    # web-security.md: the strict check runs after the cookie check, so no cookie stays 403, not 401 —
    # a valid header never stands in for the admin cookie.
    Scenario(
        "strict mode, header without cookie",
        {"WEB_AUTH_TOKEN": TOKEN, "WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE": "1", **AUTH0},
        cookie=False,
        headers=BEARER,
        expect={AUTH_FIRST: (403, NOT_ADMIN), ADMIN_FIRST: (403, NOT_ADMIN), VIEW: (403, NOT_ADMIN)},
    ),
    # #137: Bearer/Basic satisfies require_auth but never require_admin.
    Scenario(
        "Basic header only, Auth0 configured",
        {**BASIC_ENV, **AUTH0},
        cookie=False,
        headers=BASIC,
        expect={AUTH_FIRST: (403, NOT_ADMIN), ADMIN_FIRST: (403, NOT_ADMIN), VIEW: (403, NOT_ADMIN)},
    ),
    Scenario(
        "Basic header only, Auth0 not configured",
        dict(BASIC_ENV),
        cookie=False,
        headers=BASIC,
        expect={
            AUTH_FIRST: (503, ADMIN_UNCONFIGURED),
            ADMIN_FIRST: (503, ADMIN_UNCONFIGURED),
            VIEW: (503, VIEW_ADMIN_UNCONFIGURED),
        },
    ),
    Scenario(
        "header only, Auth0 configured",
        {"WEB_AUTH_TOKEN": TOKEN, **AUTH0},
        cookie=False,
        headers=BEARER,
        expect={AUTH_FIRST: (403, NOT_ADMIN), ADMIN_FIRST: (403, NOT_ADMIN), VIEW: (403, NOT_ADMIN)},
    ),
    # No credentials at all: the first guard to run answers.
    Scenario(
        "anonymous, header auth and Auth0 configured",
        {"WEB_AUTH_TOKEN": TOKEN, **AUTH0},
        cookie=False,
        headers={},
        expect={AUTH_FIRST: (401, "Unauthorized"), ADMIN_FIRST: (403, NOT_ADMIN), VIEW: (403, NOT_ADMIN)},
    ),
    Scenario(
        "anonymous, Auth0 only",
        dict(AUTH0),
        cookie=False,
        headers={},
        expect={AUTH_FIRST: (401, "Unauthorized"), ADMIN_FIRST: (403, NOT_ADMIN), VIEW: (403, NOT_ADMIN)},
    ),
    Scenario(
        "anonymous, header auth only",
        {"WEB_AUTH_TOKEN": TOKEN},
        cookie=False,
        headers={},
        expect={
            AUTH_FIRST: (401, "Unauthorized"),
            ADMIN_FIRST: (503, ADMIN_UNCONFIGURED),
            VIEW: (503, VIEW_ADMIN_UNCONFIGURED),
        },
    ),
    # #137: no Auth0 on the dyno, a Bearer header alone must not analyze/publish/curate/manage the library.
    Scenario(
        "header only, Auth0 not configured",
        {"WEB_AUTH_TOKEN": TOKEN},
        cookie=False,
        headers=BEARER,
        expect={
            AUTH_FIRST: (503, ADMIN_UNCONFIGURED),
            ADMIN_FIRST: (503, ADMIN_UNCONFIGURED),
            VIEW: (503, VIEW_ADMIN_UNCONFIGURED),
        },
    ),
    # #137: the dev opt-out for header auth does not open admin routes.
    Scenario(
        "unauthenticated allowed, Auth0 not configured",
        {"WEB_ALLOW_UNAUTHENTICATED": "1"},
        cookie=False,
        headers={},
        expect={
            AUTH_FIRST: (503, ADMIN_UNCONFIGURED),
            ADMIN_FIRST: (503, ADMIN_UNCONFIGURED),
            VIEW: (503, VIEW_ADMIN_UNCONFIGURED),
        },
    ),
    # #137: an orchestrator tenant with auth0=None on a dyno with only header auth — per-tenant 403,
    # not header pass-through. The view dependency checks the dyno's admin config first (503).
    Scenario(
        "orchestrated tenant without Auth0, header only",
        {"WEB_AUTH_TOKEN": TOKEN},
        cookie=False,
        headers=BEARER,
        expect={
            AUTH_FIRST: (403, TENANT_DISABLED),
            ADMIN_FIRST: (403, TENANT_DISABLED),
            VIEW: (503, VIEW_ADMIN_UNCONFIGURED),
        },
        orchestrated_tenant_without_auth0=True,
    ),
)


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


class _StubService:
    """Stands in for ``WebImageService`` so every admin route can reach a 200.

    Storage is the real ``ManagedStorage`` over a ``FakeS3`` holding ``img.jpg``.
    """

    def __init__(self, storage: Any) -> None:
        self.storage = storage
        self.config = SimpleNamespace(
            # Non-None -> library routes are available; the value itself is unused.
            managed=SimpleNamespace(bucket="bucket"),
            auth0=None,
            content=ContentConfig(),
            features=FeaturesConfig(
                auto_view_enabled=False,  # forces the admin check in verify_view_permissions
                library_enabled=True,
                delete_enabled=True,
            ),
            storage_paths=StoragePathConfig(image_folder=f"/{MANAGED_KEY_PREFIX}"),
        )
        image = ImageResponse(filename="img.jpg", temp_url="https://r2.example/img.jpg", has_sidecar=False)
        self.list_images = AsyncMock(return_value={"filenames": ["img.jpg"], "count": 1})
        self.get_random_image = AsyncMock(return_value=image)
        self.get_image_details = AsyncMock(return_value=image)
        self.get_thumbnail = AsyncMock(return_value=b"\xff\xd8thumb")
        self.analyze_and_caption = AsyncMock(
            return_value=AnalysisResponse(
                filename="img.jpg", description="d", mood="m", tags=["t"], nsfw=False, caption="c"
            )
        )
        self.publish_image = AsyncMock(
            return_value=PublishResponse(filename="img.jpg", results={}, archived=False, any_success=True)
        )
        self.keep_image = AsyncMock(
            return_value=CurationResponse(filename="img.jpg", action="keep", destination_folder="keep")
        )
        self.remove_image = AsyncMock(
            return_value=CurationResponse(filename="img.jpg", action="remove", destination_folder="reject")
        )
        self.delete_image = AsyncMock(
            return_value=CurationResponse(filename="img.jpg", action="delete", destination_folder="")
        )
        self.ensure_known_image = AsyncMock(return_value=None)

    def invalidate_image_listing(self) -> None:
        """No cached listing to drop in the stub."""


def _orchestrate_tenant_without_auth0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every request to an orchestrator tenant whose runtime config has ``auth0=None``.

    The orchestrator is an external service: its config source and the tenant service factory
    are replaced at the middleware's lookup; the request service stays the stub.
    """
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    tenant_config = SimpleNamespace(auth0=None, features=SimpleNamespace(auto_view_enabled=False))
    runtime = SimpleNamespace(host=TENANT_HOST, tenant="tenant-a", config=tenant_config)

    class _FakeOrchestratorSource:
        async def get_config(self, _host: str) -> SimpleNamespace:
            return runtime

    class _FakeFactory:
        async def get_service(self, _source: object, _runtime: object) -> SimpleNamespace:
            return SimpleNamespace(config=tenant_config)

    monkeypatch.setattr("publisher_v2.web.middleware.get_config_source", lambda: _FakeOrchestratorSource())
    monkeypatch.setattr("publisher_v2.web.middleware._tenant_service_factory", lambda _settings=None: _FakeFactory())


@pytest.fixture
def matrix_client(
    monkeypatch: pytest.MonkeyPatch, env_first_config: None, _clear_rate_limit: None
) -> Iterator[Callable[[Scenario], TestClient]]:
    """Build a real-app client configured for one scenario, with the stub service behind it."""
    from publisher_v2.services.managed_storage import ManagedStorage
    from publisher_v2.web.app import app
    from publisher_v2.web.dependencies import get_request_service

    s3 = FakeS3()
    s3.add(f"{MANAGED_KEY_PREFIX}/img.jpg")
    monkeypatch.setattr("publisher_v2.services.managed_storage.boto3.client", lambda *a, **k: s3)
    storage = ManagedStorage(
        ManagedStorageConfig(
            access_key_id="ak", secret_access_key="sk", endpoint_url="https://r2.example", bucket="bucket"
        )
    )

    def _make(scenario: Scenario) -> TestClient:
        for key in (
            "WEB_AUTH_TOKEN",
            "WEB_AUTH_USER",
            "WEB_AUTH_PASS",
            "WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE",
            "WEB_ALLOW_UNAUTHENTICATED",
            "FEATURE_AUTO_VIEW",
            "FEATURE_LIBRARY",
            "ORCHESTRATOR_BASE_URL",
            *AUTH0,
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
        for key, value in scenario.env.items():
            monkeypatch.setenv(key, value)
        host = "testserver"
        if scenario.orchestrated_tenant_without_auth0:
            _orchestrate_tenant_without_auth0(monkeypatch)
            host = TENANT_HOST
        app.dependency_overrides[get_request_service] = lambda: _StubService(storage)
        client = TestClient(app, base_url=f"http://{host}")
        if scenario.cookie:
            client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host=host))
        # Browser-shaped: the UI's fetch wrapper always sends this, and CSRF needs it on cookie requests.
        client.headers.update({"X-Requested-With": "XMLHttpRequest"})
        return client

    yield _make
    app.dependency_overrides.clear()


def _send(client: TestClient, route: AdminRoute, headers: dict[str, str]) -> Any:
    kwargs: dict[str, Any] = {"headers": headers}
    if route.shaping.get("upload"):
        kwargs["files"] = {"file": ("img.png", _png_bytes(), "image/png")}
    if "json" in route.shaping:
        kwargs["json"] = route.shaping["json"]
    return client.request(route.method, route.url, **kwargs)


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=lambda r: r.id)
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_admin_route_auth_matrix(
    matrix_client: Callable[[Scenario], TestClient], scenario: Scenario, route: AdminRoute
) -> None:
    """Every admin route answers each auth configuration the same way its guard order dictates."""
    status, detail = scenario.expect[route.guard]

    res = _send(matrix_client(scenario), route, scenario.headers)

    assert res.status_code == status, f"{route.id} under '{scenario.name}': {res.status_code} {res.text[:300]}"
    if detail is not None:
        assert res.json()["detail"] == detail, f"{route.id} under '{scenario.name}'"
