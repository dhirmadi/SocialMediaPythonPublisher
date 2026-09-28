"""Admin UI flows in a headless browser against the real app (PUB-084 #299 AC11, #272).

These replace the index.html source-grep tests that tried to pin this behaviour by regex over
JavaScript function bodies. Every wait is on DOM state or network traffic, never a fixed sleep.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import PurePosixPath
from typing import Any

import pytest
from botocore.exceptions import ClientError
from caption_pipeline_fakes import VISION_NEUTRAL
from playwright.sync_api import Locator, Page, Request, Route, expect

from publisher_v2.utils.captions import build_caption_sidecar

from .conftest import SEED_IMAGES, LiveApp, image_key, jpeg_bytes

pytestmark = pytest.mark.e2e

# The grid controls PUB-042 locks while an upload queue is processing.
UPLOAD_LOCKED_CONTROLS = (
    "#grid-refresh-btn",
    "#grid-sort",
    "#grid-order-toggle",
    "#grid-page-size",
    "#grid-search",
    "#grid-select-toggle",
    "#grid-delete-selected",
)
_S3_HOLD_TIMEOUT_S = 30.0


def _record(page: Page, method: str, path: re.Pattern[str]) -> list[Request]:
    """Collect every request the page issues with ``method`` whose URL path matches ``path``."""
    seen: list[Request] = []

    def _on_request(request: Request) -> None:
        if request.method == method and path.search(request.url.split("?", 1)[0]):
            seen.append(request)

    page.on("request", _on_request)
    return seen


def _open_grid(page: Page) -> None:
    with page.expect_response(lambda r: "/api/library/objects" in r.url and r.ok):
        page.locator("#btn-back-to-grid").click()
    expect(page.locator("#panel-grid")).to_be_visible()


def test_upload_queue_locks_controls_while_uploading(admin_page: Page, live_app: LiveApp) -> None:
    """PUB-042: while a file is uploading, the grid controls are disabled and the banner shows.

    The S3 put for the upload is held open, so the queue is mid-upload for as long as the test
    looks; releasing it lets the queue finish and the lock lifts.
    """
    release = threading.Event()
    real_put = live_app.s3.put_object

    def held_put(**kwargs: Any) -> dict[str, Any]:
        release.wait(timeout=_S3_HOLD_TIMEOUT_S)
        return real_put(**kwargs)

    live_app.s3.put_object = held_put  # type: ignore[method-assign]
    page = admin_page
    _open_grid(page)
    grid_panel = page.locator("#panel-grid")
    banner = page.locator("#upload-queue-status")
    try:
        with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/library/upload")) as upload:
            page.locator("#grid-upload-input").set_input_files(
                files=[{"name": "delta.jpg", "mimeType": "image/jpeg", "buffer": jpeg_bytes((10, 200, 10))}]
            )

        expect(banner).to_be_visible()
        expect(grid_panel).to_have_class(re.compile(r"\buploading-active\b"))
        for selector in UPLOAD_LOCKED_CONTROLS:
            expect(page.locator(selector)).to_be_disabled()
    finally:
        release.set()

    expect(page.locator("#upload-queue-summary")).to_have_text("1/1 done")
    expect(banner).to_be_hidden()
    expect(grid_panel).not_to_have_class(re.compile(r"\buploading-active\b"))
    for selector in UPLOAD_LOCKED_CONTROLS:
        expect(page.locator(selector)).to_be_enabled()
    assert image_key("delta.jpg") in live_app.s3.objects
    # The upload is a raw XHR on the admin cookie, outside the fetch() wrapper: it must carry the
    # CSRF header itself, or the middleware answers 403. (Read once the held request has finished:
    # all_headers() waits for the response.)
    assert upload.value.all_headers().get("x-requested-with") == "XMLHttpRequest"
    # The finished queue refreshes the grid, so the uploaded file shows without a manual refresh.
    expect(page.locator('#grid-container [data-filename="delta.jpg"]')).to_be_visible()


def test_bulk_delete_retries_failed_items(admin_page: Page, live_app: LiveApp) -> None:
    """PUB-037: a bulk delete marks the item S3 refused as failed; Retry deletes it on the next try."""
    flaky = image_key("bravo.jpg")
    failures_left = {flaky: 1}
    real_delete = live_app.s3.delete_object

    def delete_failing_once(**kwargs: Any) -> dict[str, Any]:
        if failures_left.get(kwargs["Key"], 0) > 0:
            failures_left[kwargs["Key"]] -= 1
            raise ClientError({"Error": {"Code": "InternalError", "Message": "try again"}}, "DeleteObject")
        return real_delete(**kwargs)

    live_app.s3.delete_object = delete_failing_once  # type: ignore[method-assign]
    page = admin_page
    deletes = _record(page, "DELETE", re.compile(r"/api/library/objects/[^/]+$"))
    _open_grid(page)
    expect(page.locator("#grid-container [data-filename]")).to_have_count(3)

    page.locator("#grid-select-toggle").click()
    page.locator("#grid-select-all").click()
    expect(page.locator("#grid-select-count")).to_have_text("3 selected")
    page.locator("#grid-delete-selected").click()
    page.get_by_role("button", name="Delete 3 images").click()

    summary = page.locator("#delete-queue-summary")
    expect(summary).to_have_text("2/3 done, 1 failed")
    assert flaky in live_app.s3.objects

    page.get_by_role("button", name="Retry for bravo.jpg").click()

    expect(summary).to_have_text("3/3 done")
    expect(page.get_by_role("button", name="Retry for bravo.jpg")).to_have_count(0)
    assert not any(image_key(name) in live_app.s3.objects for name in ("alpha.jpg", "bravo.jpg", "charlie.jpg"))
    assert [r.url.rsplit("/", 1)[-1] for r in deletes].count("bravo.jpg") == 2


@pytest.mark.parametrize("action", ["keep", "remove", "delete"])
def test_curation_action_sends_one_request(admin_page: Page, live_app: LiveApp, action: str) -> None:
    """One click on Keep/Remove/Delete sends exactly one request for that action, and it succeeds."""
    page = admin_page
    sent = _record(page, "POST", re.compile(rf"/api/images/[^/]+/{action}$"))

    # The action's own response, then the random image the page advances to, then idle buttons.
    with (
        page.expect_response(lambda r: "/api/images/random" in r.url),
        # Short, so a double send fails on the readable count below rather than a 30 s timeout.
        page.expect_response(lambda r: r.request in sent, timeout=5_000) as action_response,
    ):
        page.locator(f"#btn-{action}").click()
    expect(page.locator(f"#btn-{action}")).to_be_enabled()

    assert action_response.value.ok, f"{action} answered {action_response.value.status}"
    assert len(sent) == 1, f"one {action} click sent {len(sent)} requests: {[r.url for r in sent]}"


def test_logout_sends_one_request_after_repeated_actions(admin_page: Page) -> None:
    """#272: Logout sends exactly one POST /api/auth/logout, however often the buttons were toggled.

    Page load and every Next click run disableButtons(); each run must not add another logout
    handler.
    """
    page = admin_page
    for _ in range(3):
        with page.expect_response(lambda r: "/api/images/random" in r.url and r.ok):
            page.locator("#btn-next").click()
        expect(page.locator("#btn-next")).to_be_enabled()

    logouts = _record(page, "POST", re.compile(r"/api/auth/logout$"))
    with page.expect_response(lambda r: r.request in logouts):
        page.locator("#btn-admin-logout").click()
    # Logged out: the page reloaded on "/" and offers the login button again.
    expect(page.locator("#btn-admin")).to_be_visible()
    expect(page.locator("#btn-admin-logout")).to_be_hidden()

    assert len(logouts) == 1, f"one Logout click sent {len(logouts)} POST /api/auth/logout requests"
    # The cookie-only logout passes the CSRF check through the global fetch() wrapper's header.
    assert logouts[0].all_headers().get("x-requested-with") == "XMLHttpRequest"


# --- #147: per-platform caption editors (replaces source greps of the editor/publish script) ------

# An operator edit stored the pre-#147 way: in the scalar ``caption`` only. The server spreads it
# across the platforms of the AI dict, so every editor opens on this text.
LEGACY_CAPTION = "One caption for every platform, edited before per-platform captions existed."
TELEGRAM_LIMIT = 4096
EMAIL_LIMIT = 240


def _seed_legacy_edit(live_app: LiveApp) -> None:
    """Give every seeded image a sidecar holding a legacy edit next to the AI's per-platform dict."""
    sidecar = build_caption_sidecar(
        "sd prompt",
        {
            "caption": LEGACY_CAPTION,
            "caption_edited": "True",
            "caption_generated": {"telegram": "AI telegram", "email": "AI email"},
        },
    ).encode()
    for name in SEED_IMAGES:
        live_app.s3.add(image_key(f"{PurePosixPath(name).stem}.txt"), sidecar)


@pytest.fixture
def legacy_edit_page(live_app: LiveApp, page: Page, request: pytest.FixtureRequest) -> Page:
    """``admin_page``, opened only after every seeded image got its legacy-edit sidecar."""
    _seed_legacy_edit(live_app)
    admin: Page = request.getfixturevalue("admin_page")
    return admin


def _answer_publish(page: Page) -> list[Any]:
    """Answer POST /api/images/<name>/publish in the browser; return the JSON bodies it was sent."""
    bodies: list[Any] = []

    def _answer(route: Route) -> None:
        bodies.append(route.request.post_data_json)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"any_success": False, "archived": False, "results": {}}),
        )

    page.route("**/api/images/*/publish", _answer)
    return bodies


def _editor(page: Page, platform: str) -> Locator:
    return page.locator(f'#caption-editors .caption-editor[data-platform="{platform}"]')


def _publish_and_confirm(page: Page) -> None:
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/publish"), timeout=5_000):
        page.locator("#btn-publish").click()
        page.get_by_role("button", name="Confirm & Publish").click()
    expect(page.locator("#btn-publish")).to_be_enabled()


def test_caption_editors_count_against_each_platforms_own_limit(legacy_edit_page: Page) -> None:
    """#147: each editor's counter uses its platform's limit — not one fixed 240 for everyone."""
    page = legacy_edit_page
    telegram, email = _editor(page, "telegram"), _editor(page, "email")

    expect(telegram.locator("textarea")).to_have_value(LEGACY_CAPTION)
    expect(email.locator("textarea")).to_have_value(LEGACY_CAPTION)
    expect(telegram.locator(".char-count")).to_have_text(f"{len(LEGACY_CAPTION)} / {TELEGRAM_LIMIT}")
    expect(email.locator(".char-count")).to_have_text(f"{len(LEGACY_CAPTION)} / {EMAIL_LIMIT}")

    text = "knots " * 50  # 299 characters once trimmed: over email's limit, well under Telegram's
    telegram.locator("textarea").fill(text)
    email.locator("textarea").fill(text)
    length = len(text.strip())
    expect(telegram.locator(".char-count")).to_have_text(f"{length} / {TELEGRAM_LIMIT}")
    expect(telegram.locator(".char-count")).not_to_have_class(re.compile(r"\bover-limit\b"))
    expect(email.locator(".char-count")).to_have_text(f"{length} / {EMAIL_LIMIT}")
    expect(email.locator(".char-count")).to_have_class(re.compile(r"\bover-limit\b"))


def test_publish_sends_the_legacy_shape_until_a_caption_is_edited(legacy_edit_page: Page) -> None:
    """#147: an untouched spread legacy caption goes back as ``{caption}``, not N identical copies.

    Once the operator edits one editor, the publish carries every platform's own text as ``{captions}``.
    """
    page = legacy_edit_page
    bodies = _answer_publish(page)
    expect(_editor(page, "email").locator("textarea")).to_have_value(LEGACY_CAPTION)

    _publish_and_confirm(page)
    assert bodies == [{"caption": LEGACY_CAPTION}]

    edited = "Telegram gets its own line now."
    _editor(page, "telegram").locator("textarea").fill(edited)
    _publish_and_confirm(page)
    assert bodies == [{"caption": LEGACY_CAPTION}, {"captions": {"telegram": edited, "email": LEGACY_CAPTION}}]


def test_publish_is_stopped_when_one_platform_caption_is_empty(legacy_edit_page: Page) -> None:
    """#147: a partly filled set never reaches the server; the operator is told which caption is missing."""
    page = legacy_edit_page
    bodies = _answer_publish(page)

    _editor(page, "telegram").locator("textarea").fill("Only Telegram was written.")
    _editor(page, "email").locator("textarea").fill("")
    page.locator("#btn-publish").click()

    expect(page.locator("#status")).to_have_text(
        "Write a caption for FetLife (email), or clear all captions to let AI write them."
    )
    expect(page.get_by_role("button", name="Confirm & Publish")).to_have_count(0)
    assert bodies == []


# --- PUB-084 wave 5: the two admin actions #277's JS dedup left without a browser test ------------

SCRIPTED_SD_CAPTION = "kneeling figure in jute rope, hard window light, fine-art study"
# Distinct per platform, so the single-caption fallback (the same text in every editor) cannot pass.
SCRIPTED_CAPTIONS = {
    "telegram": "Telegram: the frayed rope end stayed, on purpose.",
    "email": "FetLife: a quiet floor, one harness, the last knot still settling.",
}


def test_analyze_shows_the_generated_captions(admin_page: Page, live_app: LiveApp) -> None:
    """One Analyze click sends one analyze request and fills each platform's editor with its own caption.

    The server's OpenAI client is the harness's ``FakeOpenAI``, scripted here: the vision reply,
    then the per-platform captions. Nothing is published.
    """
    page, fake = admin_page, live_app.openai
    fake.script = [{**VISION_NEUTRAL, "sd_caption": SCRIPTED_SD_CAPTION}, SCRIPTED_CAPTIONS]
    analyzes = _record(page, "POST", re.compile(r"/api/images/[^/]+/analyze$"))
    publishes = _record(page, "POST", re.compile(r"/api/images/[^/]+/publish$"))

    with page.expect_response(lambda r: r.request in analyzes, timeout=15_000) as analyze_response:
        page.locator("#btn-analyze").click()
    expect(page.locator("#btn-analyze")).to_be_enabled()

    assert analyze_response.value.ok, f"analyze answered {analyze_response.value.status}"
    # Checked before the DOM: a second request would overwrite the status and editors with its own outcome.
    assert len(analyzes) == 1, f"one Analyze click sent {len(analyzes)} requests: {[r.url for r in analyzes]}"
    expect(page.locator("#status")).to_have_text("Analysis complete; caption generated.")
    expect(page.locator("#caption-editors .caption-editor")).to_have_count(len(SCRIPTED_CAPTIONS))
    for platform, caption in SCRIPTED_CAPTIONS.items():
        expect(_editor(page, platform).locator("textarea")).to_have_value(caption)
    # The server really went through the (fake) OpenAI client: a vision call, then a caption call.
    assert fake.vision_calls, "the analyze request never reached the vision stage"
    assert fake.caption_calls, "the analyze request never reached the caption stage"
    assert publishes == []


def test_grid_single_delete_removes_the_image(admin_page: Page, live_app: LiveApp) -> None:
    """A tile's own delete control (confirm accepted) deletes that one object and drops its tile."""
    page = admin_page
    deletes = _record(page, "DELETE", re.compile(r"/api/library/objects/[^/]+$"))
    library_lists = _record(page, "GET", re.compile(r"/api/library/objects$"))
    _open_grid(page)
    total = len(SEED_IMAGES)
    tiles = page.locator("#grid-container [data-filename]")
    expect(tiles).to_have_count(total)
    expect(page.locator("#grid-result-count")).to_have_text(f"Showing 1–{total} of {total}")
    lists_before = len(library_lists)

    tile = page.locator('#grid-container [data-filename="bravo.jpg"]')
    with page.expect_response(lambda r: r.request in deletes, timeout=5_000) as delete_response:
        tile.locator("button.delete-overlay").click()

    assert delete_response.value.ok, f"delete answered {delete_response.value.status}"
    expect(tile).to_have_count(0)
    expect(tiles).to_have_count(total - 1)
    expect(page.locator("#grid-result-count")).to_have_text(f"Showing 1–{total - 1} of {total - 1}")
    assert len(deletes) == 1, f"one delete click sent {len(deletes)} requests: {[r.url for r in deletes]}"
    assert deletes[0].url.rsplit("/", 1)[-1] == "bravo.jpg"
    assert image_key("bravo.jpg") not in live_app.s3.objects
    assert all(image_key(name) in live_app.s3.objects for name in ("alpha.jpg", "charlie.jpg"))
    # The tile went because the page dropped it, not because the grid was listed again.
    assert len(library_lists) == lists_before
