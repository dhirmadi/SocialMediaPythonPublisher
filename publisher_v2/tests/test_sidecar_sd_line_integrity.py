"""PUB-051 security-audit follow-up: the sidecar's SD line (line 1) is data, not scratch space.

Three data-integrity decisions, each pinned end to end on both writers that touch line 1:

1. A run that generates captions but no new SD prompt keeps the SD prompt the
   sidecar already had, rather than blanking it (workflow and web Analyze).
2. An override publish never moves the operator's social caption into the SD
   slot, and web Analyze never serves it back as ``sd_caption``.
3. Web Analyze treats a cached sidecar with an empty SD line as a cache miss
   when SD prompts are enabled (so the prompt gets generated), and as a hit when
   they are disabled.

Only external boundaries are faked: the OpenAI client (``caption_pipeline_fakes``),
the storage backend and publishers. The workflow, AI service, sidecar writers and
parser are the real code. The web service's AI calls are stubbed at the same seam
as the neighbouring web-service tests, with the caption-only fallback blocked so
nothing can reach api.openai.com.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from caption_pipeline_fakes import (
    FakeOpenAI,
    ScriptedPublisher,
    SidecarStorage,
    default_vision_payload,
    install_fake_openai,
    openai_config,
    pipeline_config,
    real_ai_service,
)

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view
from publisher_v2.services.storage_protocol import FileMetadata
from publisher_v2.utils.captions import build_caption_sidecar

FILENAME = "a.jpg"
EXISTING_SD = "an earlier stable diffusion prompt, kneeling figure, window light"
OVERRIDE = "Operator's own social caption, typed by hand."
CACHED_CAPTION = "Cold floorboards, warm hands."

# Why a run ends up with no new SD prompt: the vision call omitted it, or the tenant has SD prompts off.
NO_NEW_SD = ["vision_omitted_sd_caption", "sd_caption_disabled"]


def _sidecar(sd_line: str, **meta: Any) -> str:
    return build_caption_sidecar(sd_line, {"image_file": FILENAME, **meta})


def _vision_without_sd(call_number: int, kwargs: dict[str, Any]) -> str:
    payload = json.loads(default_vision_payload(call_number, kwargs))
    payload.pop("sd_caption", None)
    return json.dumps(payload)


# --- workflow ------------------------------------------------------------------


async def _workflow_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    existing_sidecar: str,
    *,
    sd_enabled: bool = True,
    vision_sd: bool = True,
    caption_override: str | None = None,
) -> SidecarStorage:
    """One real WorkflowOrchestrator publish of ``FILENAME`` over a pre-existing sidecar."""
    from publisher_v2.core.workflow import WorkflowOrchestrator

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    fake = FakeOpenAI(["telegram"]) if vision_sd else FakeOpenAI(["telegram"], vision_payload=_vision_without_sd)
    install_fake_openai(monkeypatch, fake)
    storage = SidecarStorage([FILENAME])
    storage.sidecars[FILENAME] = existing_sidecar
    cfg = openai_config(sd_caption_enabled=sd_enabled)
    orchestrator = WorkflowOrchestrator(
        pipeline_config(telegram=True, openai=cfg),
        storage,
        real_ai_service(cfg),
        [ScriptedPublisher("telegram", [True])],
        tenant="t1",
    )
    result = await orchestrator.execute(select_filename=FILENAME, caption_override=caption_override)
    assert result.success, result.error
    return storage


# --- web Analyze -------------------------------------------------------------


def _web_service(
    monkeypatch: pytest.MonkeyPatch,
    sidecars: dict[str, str],
    *,
    sd_enabled: bool = True,
    vision_sd: str | None = None,
) -> Any:
    """A real WebImageService over an in-memory sidecar store; AI stubbed at the service seam."""
    monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
    monkeypatch.setenv("PUBLISHERS", json.dumps([{"type": "telegram", "channel_id": "@chan"}]))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg")
    monkeypatch.setenv("OPENAI_SETTINGS", json.dumps({"sd_caption_enabled": sd_enabled}))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
    monkeypatch.setenv("CONTENT_SETTINGS", "{}")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

    with patch("publisher_v2.services.storage.dropbox.Dropbox"):
        from publisher_v2.web.service import WebImageService

        service = WebImageService()
    assert service.config.openai.sd_caption_enabled is sd_enabled

    async def _download_sidecar(_folder: str, filename: str) -> bytes | None:
        text = sidecars.get(filename)
        return text.encode() if text is not None else None

    async def _write_sidecar(_folder: str, filename: str, text: str) -> None:
        sidecars[filename] = text

    service.storage.list_images = AsyncMock(return_value=[FILENAME])  # type: ignore[method-assign]
    service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]
    service.storage.get_temporary_link = AsyncMock(return_value="http://temp")  # type: ignore[method-assign]
    service.storage.download_sidecar_if_exists = AsyncMock(side_effect=_download_sidecar)  # type: ignore[method-assign]
    service.storage.write_sidecar_text = AsyncMock(side_effect=_write_sidecar)  # type: ignore[method-assign]
    service.storage.get_file_metadata = AsyncMock(  # type: ignore[method-assign]
        return_value=FileMetadata(file_id="id:1", revision="rev-1", modified_at=None, size=None)
    )

    analysis = ImageAnalysis(
        description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[], sd_caption=vision_sd
    )
    service.ai_service.analyzer.analyze = AsyncMock(return_value=(analysis, None))  # type: ignore[method-assign, union-attr]
    # PUB-051 AC4/AC5: a 4-tuple (captions, None, usages, angles); the SD prompt comes from vision, not here.
    service.ai_service.create_multi_caption_pair_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
        return_value=({"telegram": "fresh AI caption"}, None, [], {"telegram": "moment"})
    )
    # No real OpenAI call if the multi path ever fails: the caption-only fallback would
    # otherwise reach api.openai.com with the test key.
    service.ai_service.create_caption_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
        side_effect=AssertionError("caption-only fallback ran; the multi-caption path failed")
    )
    return service


# --- 1. no new SD prompt keeps the existing one --------------------------------


@pytest.mark.parametrize("writer", ["workflow", "web_analyze"])
@pytest.mark.parametrize("reason", NO_NEW_SD)
async def test_sidecar_write_without_new_sd_prompt_keeps_the_existing_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, writer: str, reason: str
) -> None:
    """Captions regenerated, no SD prompt this run: line 1 keeps the prompt the sidecar already had."""
    existing = _sidecar(EXISTING_SD, caption_generated={"telegram": "an older draft"})
    sd_enabled = reason != "sd_caption_disabled"

    if writer == "workflow":
        # With SD disabled the fake still returns an sd_caption: the run must not use it.
        storage = await _workflow_run(
            monkeypatch, tmp_path, existing, sd_enabled=sd_enabled, vision_sd=reason != "vision_omitted_sd_caption"
        )
        written = storage.sidecars[FILENAME]
    else:
        sidecars = {FILENAME: existing}
        vision_sd = None if reason == "vision_omitted_sd_caption" else "a vision SD prompt the tenant turned off"
        service = _web_service(monkeypatch, sidecars, sd_enabled=sd_enabled, vision_sd=vision_sd)
        result = await service.analyze_and_caption(FILENAME, force_refresh=True)
        assert result.sidecar_written, "Analyze regenerated captions, so it must rewrite the sidecar"
        written = sidecars[FILENAME]

    view = rehydrate_sidecar_view(written)
    assert view["caption_generated"] != {"telegram": "an older draft"}, "the sidecar was not rewritten at all"
    assert view["sd_caption"] == EXISTING_SD, (
        f"a run with no new SD prompt blanked or replaced the existing one: line 1 is {view['sd_caption']!r}"
    )


# --- 2. an override publish never moves the social caption into the SD slot ----


@pytest.mark.parametrize("web_sd_enabled", [True, False])
async def test_override_publish_never_moves_the_social_caption_into_the_sd_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, web_sd_enabled: bool
) -> None:
    """Override publish over an empty SD line: line 1 stays empty, and Analyze never calls the caption an SD prompt."""
    existing = _sidecar("", caption_generated={"telegram": "the AI's draft"})

    storage = await _workflow_run(monkeypatch, tmp_path, existing, caption_override=OVERRIDE)

    written = storage.sidecars[FILENAME]
    view = rehydrate_sidecar_view(written)
    assert view["caption"] == OVERRIDE, "the override publish did not record the published caption"
    first_line = written.split("\n", 1)[0]
    assert first_line == "", f"the social caption was written into the SD slot: line 1 is {first_line!r}"
    assert not view["sd_caption"], view["sd_caption"]

    # Web Analyze on the sidecar the override publish left behind.
    service = _web_service(monkeypatch, {FILENAME: written}, sd_enabled=web_sd_enabled)
    result = await service.analyze_and_caption(FILENAME)
    assert result.sd_caption != OVERRIDE, "web Analyze served the operator's social caption as the SD prompt"


# --- 3. web cache: an empty SD line is a miss only when SD prompts are on ------


@pytest.mark.parametrize("sd_enabled", [True, False])
async def test_web_cache_regenerates_when_sd_enabled_and_cached_sd_line_empty(
    monkeypatch: pytest.MonkeyPatch, sd_enabled: bool
) -> None:
    """A cached social caption over an empty SD line: regenerate when SD is on; serve the cache when it is off."""
    sidecars = {FILENAME: _sidecar("", caption_generated={"telegram": CACHED_CAPTION})}
    service = _web_service(monkeypatch, sidecars, sd_enabled=sd_enabled, vision_sd="a fresh vision SD prompt")

    with patch("publisher_v2.services.sidecar.generate_and_upload_sidecar", new=AsyncMock(return_value=1.0)):
        result = await service.analyze_and_caption(FILENAME)

    if sd_enabled:
        assert result.cached is False, "SD prompts are on and the cached SD line is empty: this must be a cache miss"
        service.ai_service.analyzer.analyze.assert_awaited_once()  # type: ignore[union-attr]
        assert result.sd_caption == "a fresh vision SD prompt"
    else:
        assert result.cached is True, "SD prompts are off, so an empty SD line is not a reason to regenerate"
        service.ai_service.analyzer.analyze.assert_not_awaited()  # type: ignore[union-attr]
        assert result.caption == CACHED_CAPTION
