"""Headless-browser harness for the admin UI (PUB-084 #299, AC11).

The real ``publisher_v2.web.app.app`` runs under uvicorn on a free localhost port, in a thread
of the test process, on env-first managed storage whose boto3 S3 client is the shared ``FakeS3``
(``managed_real_app`` from ``web/conftest.py``, reused, not copied). Auth0 is configured but never
called: the browser context carries an admin cookie minted with the app's own signer for the
server's ``Host``. Nothing leaves localhost.

These tests carry the ``e2e`` marker and are deselected by the default run (pyproject addopts);
run them with ``uv run pytest -m e2e`` after ``uv run playwright install chromium``.
"""

from __future__ import annotations

import io
import json
import re
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
import uvicorn
from caption_pipeline_fakes import FakeOpenAI, install_fake_openai
from PIL import Image
from playwright.sync_api import Dialog, Page, Request, expect
from web import conftest as web_conftest
from web.conftest import FETLIFE_PUBLISHER, MANAGED_KEY_PREFIX, TELEGRAM_PUBLISHER, FakeS3

# The web harness's managed-storage fixture, re-exported so this directory can request it: the
# app on env-first managed storage with boto3's S3 client replaced by the shared FakeS3.
managed_real_app = web_conftest.managed_real_app

# Every admin action the flows exercise is switched on; the rest is web/conftest.py's MANAGED_ENV.
E2E_ENV = {
    "FEATURE_LIBRARY": "true",
    "FEATURE_DELETE": "true",
    "FEATURE_KEEP_CURATE": "true",
    "FEATURE_REMOVE_CURATE": "true",
    "FEATURE_AUTO_VIEW": "false",
    # Two platforms, so the per-platform caption editors (#147) have distinct limits to show. Publish
    # requests in the flows are answered by the browser (page.route), so neither publisher is called.
    "PUBLISHERS": json.dumps([TELEGRAM_PUBLISHER, FETLIFE_PUBLISHER]),
    "EMAIL_SERVER": json.dumps({"sender": "bot@example.com", "smtp_server": "smtp.example", "smtp_port": 587}),
    "EMAIL_PASSWORD": "pw",  # pragma: allowlist secret
    # Guard: should a real OpenAI SDK client ever be built despite the fake below, it talks to the
    # discard port on loopback and fails fast, instead of reaching api.openai.com.
    "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
}
SEED_IMAGES = ("alpha.jpg", "bravo.jpg", "charlie.jpg")
# The caption platforms E2E_ENV's publishers enable (FetLife captions under the email key).
E2E_PLATFORMS = ["telegram", "email"]


def jpeg_bytes(color: tuple[int, int, int] = (120, 80, 60)) -> bytes:
    """A small real JPEG (the upload route verifies image bytes; thumbnails decode them)."""
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="JPEG")
    return buf.getvalue()


def image_key(name: str) -> str:
    """The S3 key the app uses for an image in the managed root."""
    return f"{MANAGED_KEY_PREFIX}/{name}"


@dataclass
class LiveApp:
    """The running server and the S3 fake behind it."""

    base_url: str
    host: str
    s3: FakeS3
    openai: FakeOpenAI


@pytest.fixture
def live_app(managed_real_app: Callable[..., FakeS3], monkeypatch: pytest.MonkeyPatch) -> Iterator[LiveApp]:
    """Serve the real app on 127.0.0.1:<free port> with ``SEED_IMAGES`` in the bucket.

    Every ``AsyncOpenAI`` the server builds is the shared ``FakeOpenAI``, installed before the
    server starts; a test scripts it through ``live_app.openai.script``.
    """
    from publisher_v2.web.app import app

    s3 = managed_real_app(env=E2E_ENV)
    openai = install_fake_openai(monkeypatch, FakeOpenAI(E2E_PLATFORMS))
    for name in SEED_IMAGES:
        s3.add(image_key(name), jpeg_bytes())

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    # Listening before uvicorn starts means the kernel queues the browser's first connection
    # until the app is up: no readiness poll is needed.
    sock.listen()
    thread.start()
    host = f"127.0.0.1:{port}"
    try:
        yield LiveApp(base_url=f"http://{host}", host=host, s3=s3, openai=openai)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def accept_dialog(dialog: Dialog) -> None:
    """The default dialog policy of ``admin_page``: accept every native dialog."""
    dialog.accept()


def open_admin_page(live_app: LiveApp, page: Page, on_dialog: Callable[[Dialog], None] = accept_dialog) -> Page:
    """Give ``page`` a signed admin cookie, load ``/`` and wait until it has settled in admin mode.

    ``on_dialog`` answers every native dialog (``confirm``, ``beforeunload``); a flow that must
    dismiss one passes its own. Returns once the start-up random image has loaded and the admin
    controls are enabled.
    """
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    page.context.add_cookies(
        [
            {
                "name": ADMIN_COOKIE_NAME,
                "value": mint_admin_cookie_value(host=live_app.host),
                "url": live_app.base_url,
            }
        ]
    )
    page.on("dialog", on_dialog)
    with page.expect_response(lambda r: "/api/images/random" in r.url and r.ok):
        page.goto(f"{live_app.base_url}/")
    expect(page.locator("#btn-admin-logout")).to_be_visible()
    expect(page.locator("#btn-keep")).to_be_enabled()
    return page


@pytest.fixture
def admin_page(live_app: LiveApp, page: Page) -> Page:
    """A browser page holding a signed admin cookie, loaded on ``/`` and settled in admin mode.

    Native ``confirm()`` dialogs are accepted. Returns once the start-up random image has loaded
    and the admin controls are enabled.
    """
    return open_admin_page(live_app, page)


def record_requests(page: Page, method: str, path: re.Pattern[str]) -> list[Request]:
    """Collect every request the page issues with ``method`` whose URL path matches ``path``."""
    seen: list[Request] = []

    def _on_request(request: Request) -> None:
        if request.method == method and path.search(request.url.split("?", 1)[0]):
            seen.append(request)

    page.on("request", _on_request)
    return seen


def open_grid(page: Page) -> None:
    """Click Back to grid and wait until the library listing has answered and the grid shows."""
    with page.expect_response(lambda r: "/api/library/objects" in r.url and r.ok):
        page.locator("#btn-back-to-grid").click()
    expect(page.locator("#panel-grid")).to_be_visible()


_S3_HOLD_TIMEOUT_S = 30.0


@contextmanager
def held_uploads(live_app: LiveApp) -> Iterator[threading.Event]:
    """Hold every S3 put open until the yielded event is set (set on exit), keeping the queue mid-upload."""
    release = threading.Event()
    real_put = live_app.s3.put_object

    def held_put(**kwargs: Any) -> dict[str, Any]:
        release.wait(timeout=_S3_HOLD_TIMEOUT_S)
        return real_put(**kwargs)

    live_app.s3.put_object = held_put  # type: ignore[method-assign]
    try:
        yield release
    finally:
        release.set()
