"""#139: without a publish store, two concurrent publishes must not double-post.

Everything runs through the real ``publisher_v2.web.app.app`` over
``httpx.ASGITransport``, the real env-first config loader, ``WebImageService``,
``WorkflowOrchestrator`` and publishers, with DATABASE_URL unset so no publish
store exists. Fakes sit only at the external client boundaries (Dropbox SDK,
OpenAI, ``telegram.Bot``, ``smtplib.SMTP``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from .conftest import FETLIFE_PUBLISHER, TELEGRAM_PUBLISHER, RealAppEnv

TELEGRAM_CAPTION = ("Rope marks on warm skin, a long slow evening told in knots and patience. " * 10).strip()
EMAIL_CAPTION = "Rope marks on warm skin; a slow evening in knots."


@pytest.fixture
def real_app(real_app_env: Callable[..., RealAppEnv]) -> RealAppEnv:
    return real_app_env(
        publishers=[TELEGRAM_PUBLISHER, FETLIFE_PUBLISHER],
        captions={"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION},
        text_caption=EMAIL_CAPTION,
    )


@pytest.fixture
def client(real_app: RealAppEnv, admin_asgi_client: Callable[..., httpx.AsyncClient]) -> httpx.AsyncClient:
    return admin_asgi_client()


async def test_two_concurrent_publishes_post_once_per_platform(client: httpx.AsyncClient, real_app: RealAppEnv) -> None:
    """The web double-click with no DB behind it: each platform sees exactly one post."""
    first, second = await asyncio.gather(
        client.post("/api/images/img.jpg/publish", json={"caption": "One line."}),
        client.post("/api/images/img.jpg/publish", json={"caption": "One line."}),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409], (first.text, second.text)
    blocked = first if first.status_code == 409 else second
    assert blocked.json()["detail"] == "Publish already in progress", blocked.text
    assert len(real_app.sent) == 1, real_app.sent
    assert len(real_app.subjects) == 1, real_app.subjects


async def test_sequential_second_publish_is_refused_with_409(
    client: httpx.AsyncClient, real_app: RealAppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Archiving off: the image stays selectable, so only the posted-state check can block it."""
    monkeypatch.setenv("CONTENT_SETTINGS", json.dumps({"hashtag_string": "", "archive": False}))

    from publisher_v2.web.app import get_service

    get_service.cache_clear()
    first = await client.post("/api/images/img.jpg/publish", json={"caption": "One line."})
    assert first.status_code == 200, first.text
    second = await client.post("/api/images/img.jpg/publish", json={"caption": "One line."})

    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "Image already published", second.text

    assert len(real_app.sent) == 1, real_app.sent
    assert len(real_app.subjects) == 1, real_app.subjects


class TestThePublishLockMapIsBounded:
    """#139 NIT: one lock per (tenant, image) ever published, kept for the life of the process."""

    async def test_idle_locks_are_dropped_but_a_held_one_survives(self) -> None:
        import asyncio

        from publisher_v2.web import service as service_module

        loop = asyncio.get_running_loop()
        service_module._PUBLISH_LOCKS.pop(loop, None)

        held = service_module._publish_lock("t1", "held.jpg")
        await held.acquire()
        try:
            for i in range(service_module._PUBLISH_LOCK_MAX_KEYS + 50):
                service_module._publish_lock("t1", f"idle-{i}.jpg")

            per_loop = service_module._PUBLISH_LOCKS[loop]
            assert len(per_loop) <= service_module._PUBLISH_LOCK_MAX_KEYS
            # Evicting a held lock would let the next click build a fresh one and
            # lose the serialization the lock exists for.
            assert service_module._publish_lock("t1", "held.jpg") is held
        finally:
            held.release()
            service_module._PUBLISH_LOCKS.pop(loop, None)
