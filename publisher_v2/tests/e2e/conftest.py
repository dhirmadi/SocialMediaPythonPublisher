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
import socket
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
import uvicorn
from PIL import Image
from playwright.sync_api import Page, expect
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
}
SEED_IMAGES = ("alpha.jpg", "bravo.jpg", "charlie.jpg")


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


@pytest.fixture
def live_app(managed_real_app: Callable[..., FakeS3]) -> Iterator[LiveApp]:
    """Serve the real app on 127.0.0.1:<free port> with ``SEED_IMAGES`` in the bucket."""
    from publisher_v2.web.app import app

    s3 = managed_real_app(env=E2E_ENV)
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
        yield LiveApp(base_url=f"http://{host}", host=host, s3=s3)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


@pytest.fixture
def admin_page(live_app: LiveApp, page: Page) -> Page:
    """A browser page holding a signed admin cookie, loaded on ``/`` and settled in admin mode.

    Native ``confirm()`` dialogs are accepted. Returns once the start-up random image has loaded
    and the admin controls are enabled.
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
    page.on("dialog", lambda dialog: dialog.accept())
    with page.expect_response(lambda r: "/api/images/random" in r.url and r.ok):
        page.goto(f"{live_app.base_url}/")
    expect(page.locator("#btn-admin-logout")).to_be_visible()
    expect(page.locator("#btn-keep")).to_be_enabled()
    return page
