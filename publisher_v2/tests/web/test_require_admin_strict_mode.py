"""PUB-048 AC2 (#187): a uniform walk of every `require_admin` call site under strict mode.

Both directions matter:

* cookie only, no `Authorization` header -> 401 everywhere. Today three call
  sites (`app.py:476`, `:859`, `:878`) call `require_admin` *without* calling
  `require_auth` first, and the strict-mode check lives only in `require_auth`,
  so a stolen cookie alone still gets in.
* a *valid* header plus a valid cookie -> 200 everywhere. This is the
  regression guard: a naive "if strict mode is configured, raise 401" inside
  `require_admin` would reject every legitimate admin request on the nine
  routes that call `require_auth` then `require_admin`.

The call-site list is the grep of `require_admin(` over
`publisher_v2/src/publisher_v2/web/`, per the AC2 text. Storage is faked at the
`ObjectStorageProtocol` boundary; the AI/publish work is stubbed on the service
the route depends on, so each parameter exercises the real auth path and
nothing else.
"""

from __future__ import annotations

import io
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from publisher_v2.config.schema import ContentConfig, FeaturesConfig, StoragePathConfig
from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value
from publisher_v2.web.models import AnalysisResponse, CurationResponse, PublishResponse

VALID_TOKEN = "strict-mode-token"
IMAGE_FOLDER = "tenant/instance"


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


class _FakeObjectStorage:
    """Records writes; satisfies the ObjectStorageProtocol calls the library router makes.

    ``head_object`` answers from the set of keys this fake actually holds, the
    way ``tests/web/conftest.py::_FakeS3`` does: PUB-048 AC9 made the upload
    route check existence before writing, so a fake that reports every key as
    present turns a first-time upload into a 409.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        # The listing the delete/move params operate on. `img.png` is deliberately
        # absent so the upload param exercises a plain upload, not an overwrite.
        self.keys: set[str] = {f"{IMAGE_FOLDER}/img.jpg"}

    async def list_objects(self, prefix: str, cursor: str | None = None, limit: int = 1000) -> dict[str, Any]:
        self.calls.append(("list_objects", prefix))
        key = f"{prefix.strip('/')}/img.jpg".lstrip("/")
        return {
            "items": [{"key": key, "size": 1, "last_modified": "2026-01-01T00:00:00Z"}],
            "cursor": None,
            "is_truncated": False,
        }

    async def put_object(self, key: str, data: Any, content_type: str) -> None:
        self.calls.append(("put_object", key))
        self.keys.add(key)

    async def head_object(self, key: str) -> dict[str, Any] | None:
        self.calls.append(("head_object", key))
        return {"ContentLength": 1} if key in self.keys else None

    async def delete_object(self, key: str) -> None:
        self.calls.append(("delete_object", key))

    async def move_object(self, src_key: str, dst_key: str) -> None:
        self.calls.append(("move_object", f"{src_key}->{dst_key}"))


class _StubService:
    """Stands in for `WebImageService` so every route can reach a 200."""

    def __init__(self) -> None:
        self.storage = _FakeObjectStorage()
        self.config = SimpleNamespace(
            # Non-None -> library routes are available; the value itself is unused.
            managed=SimpleNamespace(bucket="b"),
            auth0=None,
            content=ContentConfig(),
            features=FeaturesConfig(
                auto_view_enabled=False,  # forces the admin check in verify_view_permissions
                library_enabled=True,
                delete_enabled=True,
            ),
            storage_paths=StoragePathConfig(image_folder=IMAGE_FOLDER),
        )
        self.list_images = AsyncMock(return_value={"filenames": ["img.jpg"], "count": 1})
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


# (call site, HTTP method, path, request kwargs) — one entry per `require_admin(` call site.
# Body shaping follows tests/web/test_library_api.py::test_endpoints_require_admin_403.
_CALL_SITES = [
    pytest.param("app.py:476", "GET", "/api/images/list", {}, id="app.py:476 verify_view_permissions"),
    pytest.param("app.py:563", "POST", "/api/images/img.jpg/analyze", {}, id="app.py:563 analyze"),
    pytest.param("app.py:600", "POST", "/api/images/img.jpg/publish", {}, id="app.py:600 publish"),
    pytest.param("app.py:650", "POST", "/api/images/img.jpg/keep", {}, id="app.py:650 keep"),
    pytest.param("app.py:683", "POST", "/api/images/img.jpg/remove", {}, id="app.py:683 remove"),
    pytest.param("app.py:716", "POST", "/api/images/img.jpg/delete", {}, id="app.py:716 delete"),
    pytest.param("app.py:859", "GET", "/api/config/voice-profile", {}, id="app.py:859 voice-profile GET"),
    pytest.param(
        "app.py:878",
        "POST",
        "/api/config/voice-profile",
        {"json": {"voice_profile": ["a line."]}},
        id="app.py:878 voice-profile POST",
    ),
    pytest.param("library.py:542", "GET", "/api/library/objects", {}, id="library.py:542 list objects"),
    pytest.param("library.py:753", "POST", "/api/library/upload", {"upload": True}, id="library.py:753 upload"),
    pytest.param("library.py:802", "DELETE", "/api/library/objects/img.jpg", {}, id="library.py:802 library delete"),
    pytest.param(
        "library.py:825",
        "POST",
        "/api/library/objects/img.jpg/move",
        {"json": {"target_folder": "keep"}},
        id="library.py:825 move",
    ),
]


@pytest.fixture
def strict_client(monkeypatch: pytest.MonkeyPatch, env_first_config: None) -> Generator[TestClient, None, None]:
    """Real app in strict mode, with a valid admin cookie and a stubbed service."""
    from publisher_v2.web.app import _ANALYZE_LIMITER_HOUR, _ANALYZE_LIMITER_MIN, _PUBLISH_LIMITER_MIN, app
    from publisher_v2.web.dependencies import get_request_service
    from publisher_v2.web.routers.library import _delete_rate_limit, _upload_rate_limit

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_AUTH_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE", "1")
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
    monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
    monkeypatch.delenv("FEATURE_AUTO_VIEW", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

    for limiter in (_ANALYZE_LIMITER_MIN, _ANALYZE_LIMITER_HOUR, _PUBLISH_LIMITER_MIN):
        limiter._events.clear()
    _upload_rate_limit.clear()
    _delete_rate_limit.clear()

    app.dependency_overrides[get_request_service] = _StubService
    client = TestClient(app)
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host="testserver"))
    # Browser-shaped: the UI's fetch wrapper always sends this, and CSRF needs it
    # on the cookie-only requests that carry no Authorization header.
    client.headers.update({"X-Requested-With": "XMLHttpRequest"})
    yield client
    app.dependency_overrides.clear()
    for limiter in (_ANALYZE_LIMITER_MIN, _ANALYZE_LIMITER_HOUR, _PUBLISH_LIMITER_MIN):
        limiter._events.clear()
    _upload_rate_limit.clear()
    _delete_rate_limit.clear()


def _send(client: TestClient, method: str, path: str, shaping: dict[str, Any], headers: dict[str, str]):
    kwargs: dict[str, Any] = {"headers": headers}
    if shaping.get("upload"):
        kwargs["files"] = {"file": ("img.png", _png_bytes(), "image/png")}
    if "json" in shaping:
        kwargs["json"] = shaping["json"]
    return client.request(method, path, **kwargs)


class TestRequireAdminStrictMode:
    @pytest.mark.parametrize(("site", "method", "path", "shaping"), _CALL_SITES)
    def test_require_admin_route_returns_401_under_strict_mode_with_cookie_only(
        self, strict_client: TestClient, site: str, method: str, path: str, shaping: dict[str, Any]
    ) -> None:
        res = _send(strict_client, method, path, shaping, headers={})

        assert res.status_code == 401, f"{site} ({method} {path}) let a cookie alone through under strict mode"
        assert res.json()["detail"] == "Header authentication required in addition to the admin cookie"

    @pytest.mark.parametrize(("site", "method", "path", "shaping"), _CALL_SITES)
    def test_require_admin_route_returns_200_under_strict_mode_with_valid_header_and_cookie(
        self, strict_client: TestClient, site: str, method: str, path: str, shaping: dict[str, Any]
    ) -> None:
        res = _send(strict_client, method, path, shaping, headers={"Authorization": f"Bearer {VALID_TOKEN}"})

        assert res.status_code == 200, f"{site} ({method} {path}) rejected a valid header + cookie: {res.text}"
