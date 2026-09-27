"""#147: the web UI must show, edit and publish each platform's own caption.

Everything runs through the real ``publisher_v2.web.app.app`` over
``httpx.ASGITransport`` with the real env-first config loader, the real
``WebImageService``, ``AIService`` (caption parsing), ``WorkflowOrchestrator``
and publishers. Fakes sit only at the external client boundaries: the Dropbox
SDK client, the OpenAI client, ``telegram.Bot`` and ``smtplib.SMTP``.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from publisher_v2.utils.captions import format_caption

from .conftest import FETLIFE_PUBLISHER, IMAGE_FOLDER, TELEGRAM_PUBLISHER, RealAppEnv

TELEGRAM_CAPTION = ("Rope marks on warm skin, a long slow evening told in knots and patience. " * 10).strip()
EMAIL_CAPTION = "Rope marks on warm skin; a slow evening in knots."


@pytest.fixture
def real_app(real_app_env: Callable[..., RealAppEnv]) -> RealAppEnv:
    # PUB-051 AC4: the caption reply carries the enabled platforms only; sd_caption is the vision call's (AC5).
    return real_app_env(
        publishers=[TELEGRAM_PUBLISHER, FETLIFE_PUBLISHER],
        captions={"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION},
        text_caption=EMAIL_CAPTION,
    )


@pytest.fixture
def client(real_app: RealAppEnv, admin_asgi_client: Callable[..., httpx.AsyncClient]) -> httpx.AsyncClient:
    return admin_asgi_client()


async def test_analyze_returns_every_platform_caption_and_email_first_caption(client: httpx.AsyncClient) -> None:
    res = await client.post("/api/images/img.jpg/analyze")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["platform_captions"] == {"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION}
    assert body["caption"] == EMAIL_CAPTION
    assert len(body["caption"]) <= 240
    assert body["platform_limits"] == {"telegram": 4096, "email": 240}


async def test_publish_with_per_platform_captions_sends_each_its_own(
    client: httpx.AsyncClient, real_app: RealAppEnv
) -> None:
    tg = "Telegram gets the long one, knots and patience and the whole evening."
    em = "FetLife gets its own short line."
    res = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": tg, "email": em}})
    assert res.status_code == 200, res.text
    assert res.json()["any_success"] is True, res.json()
    assert real_app.sent == [format_caption("telegram", tg)]
    assert real_app.subjects == [format_caption("email", em)]


async def test_publish_email_never_gets_truncated_telegram_text(
    client: httpx.AsyncClient, real_app: RealAppEnv
) -> None:
    """Operator-edited texts (not the AI's): a 700-char Telegram caption must not leak, trimmed, into email."""
    long_tg = ("The operator rewrote the long Telegram story by hand, slower and warmer this time. " * 9).strip()
    short_em = "Operator's own FetLife line."
    assert len(long_tg) > 700
    res = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": long_tg, "email": short_em}})
    assert res.status_code == 200, res.text
    assert real_app.subjects == [short_em]
    assert real_app.sent == [format_caption("telegram", long_tg)]


async def test_legacy_single_caption_still_reaches_all_platforms(
    client: httpx.AsyncClient, real_app: RealAppEnv
) -> None:
    legacy = "One caption for every platform."
    res = await client.post("/api/images/img.jpg/publish", json={"caption": legacy})
    assert res.status_code == 200, res.text
    assert real_app.sent == [format_caption("telegram", legacy)]
    assert real_app.subjects == [format_caption("email", legacy)]


async def test_cached_analyze_returns_full_generated_dict(client: httpx.AsyncClient) -> None:
    """Second analyze hits the sidecar cache: all generated captions, caption is the email one."""
    first = await client.post("/api/images/img.jpg/analyze")
    assert first.status_code == 200, first.text
    second = await client.post("/api/images/img.jpg/analyze")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["cached"] is True
    assert body["platform_captions"] == {"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION}
    assert body["caption"] == EMAIL_CAPTION
    assert body["platform_limits"] == {"telegram": 4096, "email": 240}


async def test_image_details_surface_generated_captions(client: httpx.AsyncClient) -> None:
    await client.post("/api/images/img.jpg/analyze")
    res = await client.get("/api/images/img.jpg")
    assert res.status_code == 200, res.text
    assert res.json()["caption_generated"] == {"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION}


async def test_image_details_carry_platform_limits(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/images/img.jpg")
    assert res.status_code == 200, res.text
    assert res.json()["platform_limits"] == {"telegram": 4096, "email": 240}


async def test_served_ui_has_per_platform_editors_and_no_fixed_240(client: httpx.AsyncClient) -> None:
    html = (await client.get("/")).text
    assert 'id="caption-editors"' in html
    assert 'id="caption-text"' not in html  # the single shared editor is gone
    assert "const maxLen = 240" not in html
    assert "const maxLen = platformLimits[platform];" in html
    # Publish sends the per-platform dict, not one caption for everyone — except
    # when every editor still holds the untouched legacy caption, which goes back
    # in the legacy shape rather than as N copies of the same text.
    assert "{ captions }" in html
    assert "allLegacyUnedited" in html
    # A partly filled set is stopped in the UI too (the server answers 400).
    assert "missingCaptionPlatforms(captions)" in html


async def test_partial_captions_rejected_so_email_never_borrows_telegram_text(
    client: httpx.AsyncClient, real_app: RealAppEnv
) -> None:
    """A dict missing an enabled platform must not fall back to another platform's (trimmed) text."""
    long_tg = ("Only the Telegram story was written, long and slow, knot after knot. " * 11).strip()
    res = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": long_tg}})
    assert res.status_code == 400, res.text
    assert "email" in res.text
    assert real_app.sent == []
    assert real_app.subjects == []


async def test_unknown_platform_in_captions_rejected(client: httpx.AsyncClient, real_app: RealAppEnv) -> None:
    res = await client.post(
        "/api/images/img.jpg/publish",
        json={"captions": {"telegram": "a", "email": "b", "myspace": "c"}},
    )
    assert res.status_code == 400, res.text
    assert real_app.sent == [] and real_app.subjects == []


@pytest.fixture
def no_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the image in place after publishing, as an operator retrying a platform would."""
    monkeypatch.setenv("CONTENT_SETTINGS", json.dumps({"hashtag_string": "", "archive": False, "debug": False}))


async def test_edited_captions_survive_the_publish_and_come_back(
    no_archive: None, client: httpx.AsyncClient, real_app: RealAppEnv
) -> None:
    """#147: the operator's edits must be what the UI shows afterwards.

    Collapsing the override dict to one string meant the sidecar kept the AI's
    text, so every editor refilled with the pre-edit caption and the operator's
    Telegram edit was shown nowhere — and on a retry of a failed platform, the
    replaced text would have been published again.
    """
    await client.post("/api/images/img.jpg/analyze")
    tg = "OPERATOR EDITED the telegram line, knots and patience."
    em = "OPERATOR EDITED the email line."

    published = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": tg, "email": em}})
    assert published.status_code == 200, published.text

    sidecar = (real_app.dropbox_files[f"{IMAGE_FOLDER}/img.txt"]).decode()
    assert "caption_submitted" in sidecar, sidecar
    assert tg in sidecar and em in sidecar

    details = await client.get("/api/images/img.jpg")
    assert details.status_code == 200, details.text
    assert details.json()["caption_generated"] == {"telegram": tg, "email": em}

    cached = await client.post("/api/images/img.jpg/analyze")
    assert cached.status_code == 200, cached.text
    assert cached.json()["platform_captions"] == {"telegram": tg, "email": em}
    assert cached.json()["caption"] == em, "the email editor must not refill with the AI text"


async def test_the_service_rejects_a_partial_dict_even_without_the_route(
    no_archive: None, real_app: RealAppEnv
) -> None:
    """#147: the route's guard is an early exit, not the only one.

    ``publish_image`` is reachable from scripts and future callers; a partial
    dict one level below the route used to let email receive 240 characters of
    the Telegram text — the exact bug this issue exists to close.
    """
    from publisher_v2.core.exceptions import CaptionCoverageError
    from publisher_v2.web.app import get_service

    service = get_service()

    with pytest.raises(CaptionCoverageError, match="missing="):
        await service.publish_image("img.jpg", None, caption_overrides={"telegram": "T" * 700})

    assert real_app.subjects == [], "email received something from a rejected publish"
    assert real_app.sent == []


async def test_a_multi_line_edited_caption_survives_the_round_trip(
    no_archive: None, client: httpx.AsyncClient, real_app: RealAppEnv
) -> None:
    """Refutes the review's MINOR: multi-line edits are NOT stored first-line only.

    That was true while `build_caption_sidecar` wrote `str(value)` verbatim and
    the parser kept only `# `-prefixed lines. #155's line-break encoding (the
    `!json` marker, and JSON for dicts) landed on this base first, so a
    free-form editor's newlines survive both the scalar and the per-platform
    dict. Asserted through the real app rather than argued.
    """
    await client.post("/api/images/img.jpg/analyze")
    tg = "First line of the telegram caption.\nSecond line.\n\nFourth, after a blank one."
    em = "Email line one.\nEmail line two."

    published = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": tg, "email": em}})
    assert published.status_code == 200, published.text
    # A 200 alone hid a real failure here: the email subject is a header, and a
    # multi-line one used to raise HeaderWriteError inside the publisher.
    assert published.json()["results"]["email"]["success"] is True, published.json()
    assert published.json()["results"]["telegram"]["success"] is True, published.json()
    assert real_app.subjects[-1] == " ".join(format_caption("email", em).split()), "the subject must be one line"

    details = await client.get("/api/images/img.jpg")
    assert details.json()["caption_generated"] == {"telegram": tg, "email": em}

    cached = await client.post("/api/images/img.jpg/analyze")
    assert cached.json()["platform_captions"] == {"telegram": tg, "email": em}
    # The scalar half of the round trip. Asserting the served `caption` would
    # not prove it: that value comes from the per-platform dict, which #134's
    # json.dumps already protects. This reads the scalar out of the sidecar the
    # publish wrote, which is what #155's !json encoding covers.
    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view

    written = rehydrate_sidecar_view(real_app.dropbox_files[f"{IMAGE_FOLDER}/img.txt"].decode())
    assert written["caption"] == em, "the multi-line scalar caption lost its line breaks"
    assert cached.json()["caption"] == em


class TestALegacyEditStillWins:
    """#147: a sidecar written before this change records the operator's edit in
    the scalar ``caption`` only. Preferring the AI dict for those re-creates the
    very symptom the per-platform key fixes, for every image published earlier."""

    @staticmethod
    def _view(metadata: dict[str, object]) -> dict[str, object]:
        from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view
        from publisher_v2.utils.captions import build_caption_sidecar

        return rehydrate_sidecar_view(build_caption_sidecar("sd prompt", metadata))

    def test_the_edited_scalar_is_shown_for_every_platform(self) -> None:
        from publisher_v2.web.service import _generated_captions

        view = self._view(
            {
                "caption": "OPERATOR EDITED, stored the old way",
                "caption_edited": "True",
                "caption_generated": {"telegram": "AI telegram", "email": "AI email"},
            }
        )

        assert _generated_captions(view) == {
            "telegram": "OPERATOR EDITED, stored the old way",
            "email": "OPERATOR EDITED, stored the old way",
        }

    def test_an_unedited_legacy_sidecar_still_shows_the_ai_dict(self) -> None:
        from publisher_v2.web.service import _generated_captions

        view = self._view(
            {
                "caption": "AI email",
                "caption_edited": "False",
                "caption_generated": {"telegram": "AI telegram", "email": "AI email"},
            }
        )

        assert _generated_captions(view) == {"telegram": "AI telegram", "email": "AI email"}

    def test_the_new_key_beats_a_legacy_edit(self) -> None:
        from publisher_v2.web.service import _generated_captions

        view = self._view(
            {
                "caption": "older edit",
                "caption_edited": "True",
                "caption_generated": {"telegram": "AI telegram", "email": "AI email"},
                "caption_submitted": {"telegram": "newer telegram", "email": "newer email"},
            }
        )

        assert _generated_captions(view) == {"telegram": "newer telegram", "email": "newer email"}


async def test_a_bad_caption_dict_is_400_even_for_a_missing_file(client: httpx.AsyncClient) -> None:
    """Moving the guard into the service must not turn a 400 into a 404.

    The route used to reject the dict before the filename was looked at; the
    service checks the captions first for the same reason.
    """
    res = await client.post("/api/images/nope.jpg/publish", json={"captions": {"telegram": "only one"}})

    assert res.status_code == 400, res.text
    assert "cover every enabled platform" in res.text


async def test_the_served_ui_treats_a_spread_legacy_caption_as_legacy(client: httpx.AsyncClient) -> None:
    """#147: the server spreads a legacy edit across platforms, so "came from the
    scalar" no longer identifies it — the UI has to compare the text instead, or
    an untouched legacy caption is published back as N identical copies."""
    html = (await client.get("/")).text

    assert "const fromLegacy = !!legacyCaption && text === legacyCaption;" in html
    assert "allLegacyUnedited" in html
