"""Admin UI behaviours that lost their only (source-grep) test in PUB-084 wave 3 (PUB-085, #305).

Each flow drives the real app in a headless browser, the same harness as ``test_admin_flows.py``.
Every wait is on DOM state or network traffic, never a fixed sleep. Server behaviour comes from the
real app, except where a test says it answers a request in the browser with ``page.route``.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Dialog, Page, Request, Route, expect
from playwright.sync_api import Error as PlaywrightError

from .conftest import (
    SEED_IMAGES,
    LiveApp,
    held_uploads,
    image_key,
    jpeg_bytes,
    open_admin_page,
    open_grid,
    record_requests,
)

pytestmark = pytest.mark.e2e

LIBRARY_LIST = re.compile(r"/api/library/objects$")
UPLOAD_URL = "/api/library/upload"
GRID_TILES = "#grid-container [data-filename]"
# The client's first 429 backoff (RETRY_BACKOFF_MS in index.html).
RETRY_BACKOFF_MS = 5_000
# Short, so a missing dialog or close fails in seconds rather than after the 30 s default.
_EVENT_TIMEOUT_MS = 5_000


def _query(request: Request) -> dict[str, list[str]]:
    return parse_qs(urlsplit(request.url).query)


def _upload(page: Page, *names: str) -> None:
    """Pick ``names`` in the grid's upload input (each a small real JPEG)."""
    page.locator("#grid-upload-input").set_input_files(
        files=[{"name": name, "mimeType": "image/jpeg", "buffer": jpeg_bytes((10, 200, 10))} for name in names]
    )


def _current_filename(page: Page) -> str:
    """The image the detail view shows, read from its "File:" line."""
    details = page.locator("#details")
    expect(details).to_contain_text("File: ")
    match = re.search(r"File: (\S+)", details.inner_text())
    assert match, f"no file name in the details panel: {details.inner_text()!r}"
    return match.group(1)


def _expect_current(page: Page, name: str) -> None:
    """Wait until the detail view shows ``name`` on its "File:" line.

    The image's own response arrives before the page has rendered it: until then the details panel
    still names the previous image, so a one-shot read races the page.
    """
    file_line = page.locator("#details > div").filter(has=page.locator("strong", has_text="File:"))
    expect(file_line).to_have_text(f"File: {name}")
    assert _current_filename(page) == name


# --- GH-59: back to grid ----------------------------------------------------------------------------


def test_back_to_grid_opens_the_page_holding_the_current_image(admin_page: Page, live_app: LiveApp) -> None:
    """GH-59: Back to grid asks the server for the current image's page and opens on it.

    Thirty fillers sorting before every seeded name are added after the page loaded, so the current
    (random, seeded) image sits on page 2 of 25 while the grid's own offset is still page 1.
    """
    page = admin_page
    current = _current_filename(page)
    assert current in SEED_IMAGES
    fillers = [f"a{i:02d}.jpg" for i in range(30)]
    for name in fillers:
        live_app.s3.add(image_key(name), jpeg_bytes())
    total = len(fillers) + len(SEED_IMAGES)
    lists = record_requests(page, "GET", LIBRARY_LIST)

    open_grid(page)

    assert len(lists) == 1, f"opening the grid listed {len(lists)} times"
    assert _query(lists[0]).get("anchor_key") == [current]
    expect(page.locator(f'#grid-container [data-filename="{current}"]')).to_have_class(re.compile(r"\bcurrent\b"))
    expect(page.locator("#grid-result-count")).to_have_text(f"Showing 26–{total} of {total}")
    expect(page.locator("#grid-pages button.active")).to_have_text("2")


def test_back_to_grid_falls_back_when_the_page_is_empty(live_app: LiveApp, page: Page) -> None:
    """GH-59: when the grid's last page is gone and the current image with it, the grid opens on page 1.

    30 images (page 2 holds five); the operator opens charlie.jpg from page 2, then another writer
    deletes all but three images, charlie.jpg included. Back to grid finds no anchor, gets an empty
    page 2, and must fall back to page 1 rather than show "No images found".

    The start-up image is random (any of the 30), so the grid may first open on either page; the
    flow clicks page 2 and charlie.jpg's tile itself and waits for the detail view to show it.
    """
    fillers = [f"b{i:02d}.jpg" for i in range(27)]
    for name in fillers:
        live_app.s3.add(image_key(name), jpeg_bytes())
    page = open_admin_page(live_app, page)
    open_grid(page)
    with page.expect_response(lambda r: "/api/library/objects" in r.url and r.ok):
        page.locator("#grid-pages button", has_text=re.compile(r"^2$")).click()
    expect(page.locator("#grid-result-count")).to_have_text("Showing 26–30 of 30")
    with page.expect_response(lambda r: r.url.split("?", 1)[0].endswith("/api/images/charlie.jpg") and r.ok):
        page.locator('#grid-container [data-filename="charlie.jpg"]').click()
    expect(page.locator("#panel-grid")).to_be_hidden()
    _expect_current(page, "charlie.jpg")

    survivors = {image_key(name) for name in ("alpha.jpg", "b00.jpg", "b01.jpg")}
    for key in [key for key in live_app.s3.objects if key not in survivors]:
        del live_app.s3.objects[key]
    lists = record_requests(page, "GET", LIBRARY_LIST)

    page.locator("#btn-back-to-grid").click()

    expect(page.locator(GRID_TILES)).to_have_count(3)
    expect(page.locator("#grid-result-count")).to_have_text("Showing 1–3 of 3")
    expect(page.locator("#grid-empty")).to_be_hidden()
    assert [(_query(r).get("offset"), _query(r).get("anchor_key")) for r in lists] == [
        (["25"], ["charlie.jpg"]),
        (["0"], None),
    ]


# --- PUB-044 / PUB-042: page size ------------------------------------------------------------------


def test_page_size_is_remembered_across_reloads(admin_page: Page, live_app: LiveApp) -> None:
    """PUB-044: the chosen page size survives a reload (localStorage) and is what the grid asks for.

    Back to grid opens the current image's page, and the reload shows a random image: one the page
    names, whose page of ten the test works out from the name order the grid sorts by.
    """
    page = admin_page
    fillers = [f"d{i:02d}.jpg" for i in range(12)]
    for name in fillers:
        live_app.s3.add(image_key(name), jpeg_bytes())
    names = sorted([*SEED_IMAGES, *fillers])
    total = len(names)
    open_grid(page)
    expect(page.locator("#grid-result-count")).to_have_text(f"Showing 1–{total} of {total}")

    with page.expect_request(lambda r: LIBRARY_LIST.search(r.url.split("?", 1)[0]) is not None) as changed:
        page.locator("#grid-page-size").select_option("10")
    assert _query(changed.value).get("limit") == ["10"]
    expect(page.locator("#grid-result-count")).to_have_text(f"Showing 1–10 of {total}")

    with page.expect_response(lambda r: "/api/images/random" in r.url and r.ok):
        page.reload()
    expect(page.locator("#btn-keep")).to_be_enabled()
    current = _current_filename(page)
    first = names.index(current) // 10 * 10
    page_names = names[first : first + 10]
    lists = record_requests(page, "GET", LIBRARY_LIST)
    open_grid(page)

    expect(page.locator("#grid-page-size")).to_have_value("10")
    assert [_query(r).get("limit") for r in lists] == [["10"]]
    expect(page.locator("#grid-result-count")).to_have_text(f"Showing {first + 1}–{first + len(page_names)} of {total}")
    expect(page.locator(GRID_TILES)).to_have_count(len(page_names))


def test_page_size_control_is_locked_while_uploading(admin_page: Page, live_app: LiveApp) -> None:
    """PUB-042: the page-size select is disabled while an upload runs, and keeps its value after."""
    page = admin_page
    page_size = page.locator("#grid-page-size")
    open_grid(page)
    expect(page_size).to_be_enabled()
    with page.expect_response(lambda r: "/api/library/objects" in r.url and r.ok):
        page_size.select_option("10")

    with held_uploads(live_app):
        with page.expect_request(lambda r: r.method == "POST" and r.url.endswith(UPLOAD_URL)):
            _upload(page, "delta.jpg")
        expect(page.locator("#upload-queue-status")).to_be_visible()
        expect(page_size).to_be_disabled()

    expect(page.locator("#upload-queue-summary")).to_have_text("1/1 done")
    expect(page_size).to_be_enabled()
    expect(page_size).to_have_value("10")


# --- PUB-036 / GH-60: the upload queue --------------------------------------------------------------


def test_rate_limited_upload_waits_and_retries(live_app: LiveApp, page: Page) -> None:
    """GH-60: a 429 puts the file in the waiting state; after the backoff it is sent again and completes.

    The 429 is answered in the browser (``page.route``, first upload request only): the app's own
    limiter keeps a 60 s window, longer than the client's backoff, so a real 429 would be answered
    again on every retry. Later requests go through to the real app. The page's clock is Playwright's,
    so the test jumps the backoff instead of waiting it out.
    """
    page.clock.install()
    page = open_admin_page(live_app, page)
    uploads = record_requests(page, "POST", re.compile(re.escape(UPLOAD_URL) + "$"))
    answered_429: list[int] = []

    def _limit_first(route: Route) -> None:
        if not answered_429:
            answered_429.append(429)
            route.fulfill(status=429, content_type="application/json", body=json.dumps({"detail": "Slow down"}))
        else:
            route.continue_()

    page.route(f"**{UPLOAD_URL}", _limit_first)
    open_grid(page)
    with page.expect_response(lambda r: r.url.endswith(UPLOAD_URL) and r.status == 429):
        _upload(page, "delta.jpg")

    row = page.locator("#upload-queue-list .upload-queue-item")
    expect(row).to_have_count(1)
    expect(row).to_have_class(re.compile(r"\buq-waiting\b"))
    expect(row.locator(".uq-name")).to_have_text("delta.jpg (rate limited…)")
    expect(page.locator("#upload-queue-status")).to_be_visible()
    assert len(uploads) == 1
    assert image_key("delta.jpg") not in live_app.s3.objects

    with page.expect_response(lambda r: r.url.endswith(UPLOAD_URL) and r.ok):
        page.clock.fast_forward(RETRY_BACKOFF_MS)

    expect(page.locator("#upload-queue-summary")).to_have_text("1/1 done")
    expect(row).to_have_class(re.compile(r"\buq-done\b"))
    expect(page.locator("#upload-queue-status")).to_be_hidden()
    assert len(uploads) == 2
    assert image_key("delta.jpg") in live_app.s3.objects


def test_enqueuing_clears_completed_queue_entries(admin_page: Page, live_app: LiveApp) -> None:
    """GH-60: picking new files drops the finished entries of earlier batches; failed ones stay for Retry.

    The failure is the real app's: alpha.jpg already exists, so its upload is refused with 409.
    A batch with a failure never auto-hides, so the queue is still on screen for the second pick.
    """
    page = admin_page
    names = page.locator("#upload-queue-list .uq-name")
    summary = page.locator("#upload-queue-summary")
    open_grid(page)

    _upload(page, "delta.jpg", "alpha.jpg")
    expect(summary).to_have_text("1/2 done, 1 failed")
    expect(names).to_have_text(["delta.jpg", "alpha.jpg"])

    with page.expect_response(lambda r: r.url.endswith(UPLOAD_URL) and r.ok):
        _upload(page, "echo.jpg")

    expect(names).to_have_text(["alpha.jpg", "echo.jpg"])
    expect(summary).to_have_text("1/2 done, 1 failed")
    expect(page.get_by_role("button", name="Retry for alpha.jpg")).to_be_visible()
    assert image_key("echo.jpg") in live_app.s3.objects


# --- PUB-037: multi-select keyboard and ARIA --------------------------------------------------------


def test_escape_leaves_multi_select_and_items_expose_aria(admin_page: Page) -> None:
    """PUB-037: in multi-select each tile is a focusable checkbox; Escape leaves the mode and clears it."""
    page = admin_page
    open_grid(page)
    tiles = page.locator(GRID_TILES)
    expect(tiles).to_have_count(len(SEED_IMAGES))
    bravo = page.locator('#grid-container [data-filename="bravo.jpg"]')
    charlie = page.locator('#grid-container [data-filename="charlie.jpg"]')

    page.locator("#grid-select-toggle").click()
    expect(page.locator("#grid-select-bar")).to_be_visible()
    for i in range(len(SEED_IMAGES)):
        tile = tiles.nth(i)
        expect(tile).to_have_attribute("tabindex", "0")
        expect(tile).to_have_attribute("role", "checkbox")
        expect(tile).to_have_attribute("aria-checked", "false")

    bravo.click()
    expect(bravo).to_have_attribute("aria-checked", "true")
    charlie.focus()
    page.keyboard.press("Space")
    expect(charlie).to_have_attribute("aria-checked", "true")
    expect(page.get_by_role("checkbox", checked=True)).to_have_count(2)
    expect(page.locator("#grid-select-count")).to_have_text("2 selected")

    page.keyboard.press("Escape")

    expect(page.locator("#grid-select-bar")).to_be_hidden()
    expect(page.locator("#grid-select-toggle")).to_have_text("☐ Select")
    expect(page.locator("#grid-delete-selected")).to_be_hidden()
    expect(page.get_by_role("checkbox")).to_have_count(0)
    for i in range(len(SEED_IMAGES)):
        expect(tiles.nth(i)).not_to_have_attribute("aria-checked", re.compile(".*"))
    # Leaving the mode dropped the selection: re-entering starts with nothing checked.
    page.locator("#grid-select-toggle").click()
    expect(page.get_by_role("checkbox", checked=False)).to_have_count(len(SEED_IMAGES))


# --- PUB-042: leaving the page while uploading ------------------------------------------------------


def test_leaving_the_page_while_uploading_is_guarded(live_app: LiveApp, page: Page) -> None:
    """PUB-042: closing the page mid-upload raises the beforeunload prompt; once done, it closes freely.

    The prompt is dismissed, so the page (and its upload) stays.
    """
    dialogs: list[str] = []

    def _dismiss(dialog: Dialog) -> None:
        dialogs.append(dialog.type)
        dialog.dismiss()

    page = open_admin_page(live_app, page, on_dialog=_dismiss)
    open_grid(page)  # a real click: Chromium only raises beforeunload after a user gesture
    with held_uploads(live_app):
        with page.expect_request(lambda r: r.method == "POST" and r.url.endswith(UPLOAD_URL)):
            _upload(page, "delta.jpg")
        expect(page.locator("#upload-queue-status")).to_be_visible()

        with page.expect_event("dialog", timeout=_EVENT_TIMEOUT_MS) as prompt:
            page.close(run_before_unload=True)
        assert prompt.value.type == "beforeunload"
        expect(page.locator("#upload-queue-status")).to_be_visible()
        assert not page.is_closed()

    expect(page.locator("#upload-queue-summary")).to_have_text("1/1 done")
    expect(page.locator("#upload-queue-status")).to_be_hidden()
    assert image_key("delta.jpg") in live_app.s3.objects
    with page.expect_event("close", timeout=_EVENT_TIMEOUT_MS):
        page.close(run_before_unload=True)
    assert dialogs == ["beforeunload"]


def test_selecting_a_grid_item_while_uploading_asks_first(live_app: LiveApp, page: Page) -> None:
    """PUB-042: opening an image from the grid mid-upload asks first; No stays in the grid, Yes opens it.

    Without an upload running the same click opens the image without asking.
    """
    dialogs: list[str] = []
    answers = iter([False, True])

    def _answer(dialog: Dialog) -> None:
        dialogs.append(f"{dialog.type}: {dialog.message}")
        dialog.accept() if next(answers) else dialog.dismiss()

    page = open_admin_page(live_app, page, on_dialog=_answer)
    grid = page.locator("#panel-grid")
    open_grid(page)
    with page.expect_response(lambda r: r.url.split("?", 1)[0].endswith("/api/images/alpha.jpg") and r.ok):
        page.locator('#grid-container [data-filename="alpha.jpg"]').click()
    expect(grid).to_be_hidden()
    _expect_current(page, "alpha.jpg")
    assert dialogs == []

    open_grid(page)
    opens = record_requests(page, "GET", re.compile(r"/api/images/bravo\.jpg$"))
    with held_uploads(live_app):
        with page.expect_request(lambda r: r.method == "POST" and r.url.endswith(UPLOAD_URL)):
            _upload(page, "delta.jpg")
        expect(page.locator("#upload-queue-status")).to_be_visible()
        bravo = page.locator('#grid-container [data-filename="bravo.jpg"]')

        bravo.click()
        assert dialogs == [
            "confirm: Uploads are still in progress. Leaving the grid will cancel remaining uploads. Continue?"
        ]
        expect(grid).to_be_visible()
        assert opens == []

        with page.expect_response(lambda r: r.request in opens):
            bravo.click()
        assert len(dialogs) == 2
        expect(grid).to_be_hidden()
        _expect_current(page, "bravo.jpg")


# --- #137: no password login --------------------------------------------------------------------------


def test_password_auth_mode_never_shows_a_password_prompt(live_app: LiveApp, page: Page) -> None:
    """#137: a server reporting the removed ``password`` auth mode gets no password prompt of any kind.

    The real app only reports ``auth0`` or ``none``, so the features response is the real one with
    ``auth_mode`` rewritten to ``password`` in the browser (``page.route``). The visitor is logged out.
    """
    dialogs: list[str] = []

    def _record_dialog(dialog: Dialog) -> None:
        dialogs.append(f"{dialog.type}: {dialog.message}")
        dialog.dismiss()

    def _password_mode(route: Route) -> None:
        response = route.fetch()
        route.fulfill(response=response, json={**response.json(), "auth_mode": "password"})

    home = f"{live_app.base_url}/"
    navigations: list[str] = []

    def _record_navigation(request: Request) -> None:
        if request.is_navigation_request() and request.frame == page.main_frame:
            navigations.append(request.url)

    def _click_hidden(selector: str) -> None:
        """Fire a scripted click on a hidden button, then prove it started no navigation."""
        page.locator(selector).dispatch_event("click", timeout=_EVENT_TIMEOUT_MS)
        # Barrier: a request the page starts after the click handler has run. Playwright reports a
        # page's requests in the order it issues them, so a navigation the handler started is
        # recorded by the time this fetch's request is.
        try:
            with page.expect_request(lambda r: r.url.endswith("/api/admin/status"), timeout=_EVENT_TIMEOUT_MS):
                page.evaluate("() => { fetch('/api/admin/status'); }")
        except PlaywrightError:
            # A navigation can destroy the page's context under the barrier; the assertion below names it.
            if not navigations:
                raise
        assert navigations == [], f"a scripted click on the hidden {selector} navigated to {navigations}"
        expect(page, f"a scripted click on the hidden {selector} left the page").to_have_url(
            home, timeout=_EVENT_TIMEOUT_MS
        )

    page.on("dialog", _record_dialog)
    page.route("**/api/config/features", _password_mode)
    # A regression that starts a login must not reach Auth0: the browser answers it itself.
    page.route("**/auth/**", lambda route: route.fulfill(status=200, content_type="text/html", body="login"))
    with page.expect_response(lambda r: r.url.endswith("/api/config/features")) as features:
        page.goto(home)
    assert features.value.json()["auth_mode"] == "password"
    expect(page.locator("#status")).to_have_text(re.compile(r"^Ready\. "))
    page.on("request", _record_navigation)

    expect(page.locator("#admin-unavailable")).to_be_visible()
    expect(page.locator("#btn-admin")).to_be_hidden()
    expect(page.locator("#btn-login-cta")).to_be_hidden()
    expect(page.locator("#btn-admin-logout")).to_be_hidden()
    # Even a scripted click on a (hidden) login button asks for nothing and goes nowhere.
    _click_hidden("#btn-admin")
    _click_hidden("#btn-login-cta")
    expect(page.locator("#status")).to_have_text(re.compile(r"^Ready\. "))
    expect(page.locator("input[type=password]")).to_have_count(0)
    assert dialogs == []
