from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.ai import VisionAnalyzerOpenAI


class _FakeRespMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeRespMessage(content)


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self, content: str, delay_ms: float = 0) -> None:
        self._content = content
        self._delay_ms = delay_ms

    async def create(self, *args: Any, **kwargs: Any) -> _FakeResp:
        # Simulate minimal delay to exercise timing
        if self._delay_ms:
            await asyncio.sleep(self._delay_ms / 1000.0)
        return _FakeResp(self._content)


class _FakeAsyncOpenAI:
    def __init__(self, content: str, delay_ms: float = 0) -> None:
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeChatCompletions(content, delay_ms=delay_ms)


def _build_config() -> OpenAIConfig:
    # Minimal viable OpenAIConfig for analyzer; tests do not hit real network.
    return OpenAIConfig(
        api_key="sk-test",
        vision_model="gpt-4.1-mini",
        caption_model="gpt-4.1-mini",
        vision_max_dimension=0,
        vision_fallback_enabled=False,
    )


@pytest.mark.asyncio
async def test_vision_analyzer_logs_timing_success(monkeypatch, caplog) -> None:
    config = _build_config()
    analyzer = VisionAnalyzerOpenAI(config)

    fake_client = _FakeAsyncOpenAI(
        json.dumps(
            {
                "description": "short description",
                "mood": "calm",
                "tags": ["tag1", "tag2"],
                "nsfw": False,
                "safety_labels": [],
            }
        )
    )
    monkeypatch.setattr(analyzer, "client", fake_client)

    caplog.set_level(logging.INFO, logger="publisher_v2.ai.vision")

    analysis, _usage = await analyzer.analyze("http://example.com/image.jpg")
    assert isinstance(analysis, ImageAnalysis)

    telemetry_logs = [record for record in caplog.records if "vision_analysis" in getattr(record, "message", "")]
    assert telemetry_logs, "expected at least one telemetry log_json entry"

    # Parse last telemetry JSON entry
    payload = json.loads(telemetry_logs[-1].message)
    assert payload.get("event") == "vision_analysis"
    assert payload.get("model") == config.vision_model
    assert payload.get("ok") is True
    assert payload.get("error_type") is None
    assert payload.get("vision_analysis_ms", 0) >= 0


@pytest.mark.asyncio
async def test_vision_analyzer_logs_timing_on_json_error(monkeypatch, caplog) -> None:
    """Post-hardening: a non-JSON Vision response raises AIServiceError but
    must still emit a telemetry log so error_type=json_decode_error is visible
    in dashboards."""
    from publisher_v2.core.exceptions import AIServiceError

    config = _build_config()
    analyzer = VisionAnalyzerOpenAI(config)

    fake_client = _FakeAsyncOpenAI("not-json")
    monkeypatch.setattr(analyzer, "client", fake_client)

    caplog.set_level(logging.INFO, logger="publisher_v2.ai.vision")

    with pytest.raises(AIServiceError):
        await analyzer.analyze("http://example.com/image.jpg")

    telemetry_logs = [record for record in caplog.records if "vision_analysis" in getattr(record, "message", "")]
    assert telemetry_logs, "expected telemetry log_json even on JSON error"
    payload = json.loads(telemetry_logs[-1].message)
    assert payload.get("event") == "vision_analysis"
    assert payload.get("ok") is False
    assert payload.get("error_type") == "json_decode_error"


# ---------------------------------------------------------------------------
# PUB-051 AC5/AC6: sd_caption on the neutral vision call; caption-facing fields
# under the owner persona, with a seeded senses pool; sidecar invariant holds.
#
# Design-agnostic by construction (the spec allows either a second owner-persona
# vision call or one combined two-register system message): the fake OpenAI
# client returns sensory_detail/mood_note ONLY from a call whose system message
# carries OWNER_PERSONA_MARKER, and stamps every vision call's sd_caption with
# that call's number.
# ---------------------------------------------------------------------------


async def _run_one_publish(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[Any, Any, Any]:
    """One real WorkflowOrchestrator run with fake OpenAI/storage/publisher; returns (result, fake, storage)."""
    from caption_pipeline_fakes import (
        FakeOpenAI,
        ScriptedPublisher,
        SidecarStorage,
        install_fake_openai,
        pipeline_config,
        real_ai_service,
    )

    from publisher_v2.core.workflow import WorkflowOrchestrator

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    fake = FakeOpenAI(["telegram"])
    install_fake_openai(monkeypatch, fake)
    storage = SidecarStorage(["a.jpg"])
    orchestrator = WorkflowOrchestrator(
        pipeline_config(telegram=True),
        storage,
        real_ai_service(),
        [ScriptedPublisher("telegram", [True])],
        tenant="t1",
    )
    result = await orchestrator.execute(select_filename="a.jpg")
    return result, fake, storage


async def test_sd_caption_comes_from_the_neutral_register_vision_call(monkeypatch, tmp_path) -> None:
    """AC5: sd_caption is the neutral/analyst vision call's output, written to the sidecar unchanged."""
    from caption_pipeline_fakes import SD_FROM_CALL, system_text

    from publisher_v2.config.static_loader import get_static_config
    from publisher_v2.services.ai import OWNER_PERSONA_MARKER
    from publisher_v2.services.sidecar_parser import parse_sidecar_text

    result, fake, storage = await _run_one_publish(monkeypatch, tmp_path)

    assert result.success, result.error
    vision = fake.vision_calls
    assert vision, "no vision-stage call was made"
    neutral = [n for n, call in enumerate(vision, 1) if OWNER_PERSONA_MARKER not in system_text(call)]
    if not neutral:
        # Single-call two-register design: the one call carries both registers.
        assert len(vision) == 1, "several vision calls, none of them in the neutral register"
        neutral = [1]
    assert len(neutral) == 1, f"expected exactly one neutral-register vision call, got {neutral}"
    neutral_call = vision[neutral[0] - 1]
    # The neutral call keeps the (unchanged) analyst system prompt from ai_prompts.yaml.
    assert get_static_config().ai_prompts.vision.system.strip() in system_text(neutral_call)

    assert "a.jpg" in storage.sidecars, "no sidecar written — sd_caption did not reach the workflow"
    sd_caption, _meta = parse_sidecar_text(storage.sidecars["a.jpg"])
    assert sd_caption == SD_FROM_CALL.format(n=neutral[0])


async def test_caption_facing_fields_carry_the_owner_persona_marker(monkeypatch) -> None:
    """AC5: the system message governing sensory_detail/mood_note carries the fixed marker."""
    from caption_pipeline_fakes import MOOD_NOTE, SENSORY_DETAIL, FakeOpenAI, openai_config, system_text

    from publisher_v2.services.ai import OWNER_PERSONA_MARKER

    assert OWNER_PERSONA_MARKER == "OWNER-VOICE SECTION:"
    analyzer = VisionAnalyzerOpenAI(openai_config())
    fake = FakeOpenAI([])
    monkeypatch.setattr(analyzer, "client", fake)

    analysis, _usage = await analyzer.analyze("https://example.com/a.jpg")

    governed = [c for c in fake.vision_calls if OWNER_PERSONA_MARKER in system_text(c)]
    assert governed, "no vision-stage system message carries OWNER_PERSONA_MARKER"
    # The fake only returns these from a marker-bearing call, so equality proves which call produced them.
    assert analysis.sensory_detail == SENSORY_DETAIL
    assert analysis.mood_note == MOOD_NOTE


async def test_senses_pool_prompt_text_differs_by_image_seed(monkeypatch) -> None:
    """AC6: the senses pool offered to the model is seeded from the image content hash.

    Asserted on the constructed prompt text only (the model's output cannot be).
    Seed formula per spec: ``int.from_bytes(hashlib.sha256(content).digest()[:8], "big")``.
    Four images rather than two so one unlucky seed collision cannot decide the
    test; the same image twice must give the same text.
    """
    from caption_pipeline_fakes import FakeOpenAI, jpeg_bytes, openai_config, system_text, user_text

    from publisher_v2.services.ai import OWNER_PERSONA_MARKER

    analyzer = VisionAnalyzerOpenAI(openai_config(vision_max_dimension=256))
    fake = FakeOpenAI([])
    monkeypatch.setattr(analyzer, "client", fake)
    images = [jpeg_bytes(64, 48, c) for c in [(200, 30, 30), (30, 200, 30), (30, 30, 200), (120, 120, 20)]]

    async def _owner_prompt_text(image: bytes) -> str:
        before = len(fake.calls)
        await analyzer.analyze(image)
        governed = [c for c in fake.calls[before:] if OWNER_PERSONA_MARKER in system_text(c)]
        assert governed, "no owner-persona prompt was sent"
        return "\n".join(system_text(c) + "\n" + user_text(c) for c in governed)

    texts = [await _owner_prompt_text(image) for image in images]
    again = await _owner_prompt_text(images[0])

    assert again == texts[0], "the senses pool is not deterministic for the same image"
    assert len(set(texts)) > 1, "every image got the identical senses pool — not seeded by content"


async def test_caption_facing_fields_stay_out_of_sidecar_after_vision_restructure(monkeypatch, tmp_path) -> None:
    """AC6: regression guard on the core/models.py invariant now that vision has a second register."""
    from caption_pipeline_fakes import MOOD_NOTE, SENSORY_DETAIL, system_text

    from publisher_v2.services.ai import OWNER_PERSONA_MARKER
    from publisher_v2.services.sidecar_parser import parse_sidecar_text

    result, fake, storage = await _run_one_publish(monkeypatch, tmp_path)

    assert result.success, result.error
    assert any(OWNER_PERSONA_MARKER in system_text(c) for c in fake.vision_calls), "vision stage not restructured"
    assert "a.jpg" in storage.sidecars, "no sidecar written"
    text = storage.sidecars["a.jpg"]
    _sd, meta = parse_sidecar_text(text)
    assert meta is not None and meta.get("alt_text"), "phase-2 metadata missing; the guard would be vacuous"
    assert "sensory_detail" not in meta
    assert "mood_note" not in meta
    for value in [*SENSORY_DETAIL, MOOD_NOTE]:
        assert value not in text, f"caption-facing text leaked into the sidecar: {value!r}"


# ---------------------------------------------------------------------------
# PUB-051 critique follow-up: tenant persona in the owner section, sd_caption
# only requested when enabled, and the workflow's SD telemetry.
# ---------------------------------------------------------------------------


def _log_messages(caplog, level: int | None = None) -> list[str]:
    """The ``message`` field of every log_json record captured (optionally at one level)."""
    out: list[str] = []
    for record in caplog.records:
        if level is not None and record.levelno != level:
            continue
        try:
            out.append(str(json.loads(record.getMessage()).get("message")))
        except (ValueError, AttributeError):
            out.append(record.getMessage())
    return out


async def _vision_system_message(monkeypatch, cfg: OpenAIConfig) -> str:
    from caption_pipeline_fakes import FakeOpenAI, system_text

    analyzer = VisionAnalyzerOpenAI(cfg)
    fake = FakeOpenAI([])
    monkeypatch.setattr(analyzer, "client", fake)
    await analyzer.analyze("https://example.com/a.jpg")
    assert len(fake.vision_calls) == 1
    return system_text(fake.vision_calls[0])


async def test_vision_owner_section_uses_the_tenant_persona_when_set(monkeypatch) -> None:
    """A tenant caption persona (``OpenAIConfig.system_prompt``) reaches the OWNER-VOICE SECTION, truncated.

    Without one, the default owner section is used. Either way the marker is
    present and the neutral ``vision.system`` text is unchanged and precedes it.
    """
    from caption_pipeline_fakes import openai_config

    from publisher_v2.config.static_loader import get_static_config
    from publisher_v2.services.ai import OWNER_PERSONA_MARKER

    head = "I am Mara, and I tie rope in a cold studio above a bakery in Leith."
    tail = "ZQTAILSENTINEL the end of a very long tenant persona."
    # Far longer than any sensible bound, so a bounded section cannot carry the tail.
    persona = f"{head} " + ("I work slowly and I talk to the people I tie with. " * 80) + tail
    neutral = get_static_config().ai_prompts.vision.system.strip()

    tenant_msg = await _vision_system_message(monkeypatch, openai_config(system_prompt=persona))
    default_msg = await _vision_system_message(monkeypatch, openai_config())

    for msg in (tenant_msg, default_msg):
        assert OWNER_PERSONA_MARKER in msg
        assert neutral in msg, "the neutral vision.system text changed"
        assert msg.index(neutral) < msg.index(OWNER_PERSONA_MARKER), "the neutral text must precede the marker"

    tenant_neutral, tenant_owner = tenant_msg.split(OWNER_PERSONA_MARKER, 1)
    assert head in tenant_owner, "the tenant persona did not reach the owner-voice section"
    assert head not in tenant_neutral, "the tenant persona leaked into the neutral register"
    assert tail not in tenant_msg, "the tenant persona was not truncated to a bounded length"

    default_owner = default_msg.split(OWNER_PERSONA_MARKER, 1)[1]
    schema_default_persona = OpenAIConfig.model_fields["system_prompt"].default
    assert schema_default_persona not in default_owner, "no tenant persona: the default owner section must be used"
    assert head not in default_owner


async def test_vision_does_not_request_sd_caption_when_disabled(monkeypatch, caplog) -> None:
    """``sd_caption_enabled=False``: neither vision message asks for an ``sd_caption`` key, and nothing warns."""
    from caption_pipeline_fakes import VISION_NEUTRAL, FakeOpenAI, openai_config, system_text, user_text

    analyzer = VisionAnalyzerOpenAI(openai_config(sd_caption_enabled=False))
    fake = FakeOpenAI([], vision_payload=lambda _n, _kw: json.dumps(dict(VISION_NEUTRAL)))
    monkeypatch.setattr(analyzer, "client", fake)
    caplog.set_level(logging.INFO, logger="publisher_v2.ai.vision")

    await analyzer.analyze("https://example.com/a.jpg")

    assert len(fake.vision_calls) == 1
    call = fake.vision_calls[0]
    assert "sd_caption" not in user_text(call), "the vision user message still requests sd_caption"
    assert "sd_caption" not in system_text(call), "the vision system message still requests sd_caption"
    assert "vision_sd_caption_missing" not in _log_messages(caplog)


async def test_vision_warns_when_sd_caption_missing_and_enabled(monkeypatch, caplog) -> None:
    """``sd_caption_enabled=True`` and a reply without ``sd_caption``: one WARNING, no model output echoed."""
    from caption_pipeline_fakes import VISION_NEUTRAL, FakeOpenAI, openai_config

    analyzer = VisionAnalyzerOpenAI(openai_config(sd_caption_enabled=True))
    fake = FakeOpenAI([], vision_payload=lambda _n, _kw: json.dumps(dict(VISION_NEUTRAL)))
    monkeypatch.setattr(analyzer, "client", fake)
    caplog.set_level(logging.INFO, logger="publisher_v2.ai.vision")

    analysis, _usage = await analyzer.analyze("https://example.com/a.jpg")

    assert analysis.sd_caption is None
    assert _log_messages(caplog, logging.WARNING).count("vision_sd_caption_missing") == 1
    warning = next(r for r in caplog.records if "vision_sd_caption_missing" in r.getMessage())
    assert VISION_NEUTRAL["description"] not in warning.getMessage()


async def test_workflow_logs_sd_caption_from_vision_not_caption_stage_events(monkeypatch, tmp_path, caplog) -> None:
    """The caption call no longer produces an SD prompt: no ``sd_caption_start``/``sd_caption_complete``;
    one ``sd_caption_from_vision`` INFO event instead, carrying no content.
    """
    from caption_pipeline_fakes import SD_FROM_CALL

    caplog.set_level(logging.INFO)

    result, _fake, _storage = await _run_one_publish(monkeypatch, tmp_path)

    assert result.success, result.error
    messages = _log_messages(caplog)
    assert "sd_caption_start" not in messages
    assert "sd_caption_complete" not in messages
    info = _log_messages(caplog, logging.INFO)
    assert info.count("sd_caption_from_vision") == 1, "expected exactly one sd_caption_from_vision INFO event"
    record = next(r for r in caplog.records if '"sd_caption_from_vision"' in r.getMessage())
    assert SD_FROM_CALL.split("{")[0] not in record.getMessage(), "the SD prompt text must not be logged"


# ---------------------------------------------------------------------------
# PUB-051 last round: a custom static dir without vision.sd_caption (W4), and
# the senses-seed hash off the event loop.
# ---------------------------------------------------------------------------


@pytest.fixture
def _fresh_static_config():
    """Clear the cached static config before and after, so a tmp PV2_STATIC_CONFIG_DIR takes effect and never leaks."""
    from publisher_v2.config.static_loader import get_static_config

    get_static_config.cache_clear()
    yield
    get_static_config.cache_clear()


def _write_custom_static_dir(tmp_path, vision: dict[str, Any]) -> str:
    import yaml

    (tmp_path / "ai_prompts.yaml").write_text(yaml.safe_dump({"vision": vision}), encoding="utf-8")
    return str(tmp_path)


_PACKAGED_STATIC_DIR = str(Path(__file__).resolve().parents[1] / "src" / "publisher_v2" / "config" / "static")
_CUSTOM_VISION_USER = "CUSTOMDIR user instructions: return one JSON object describing this image."


async def test_static_config_without_vision_sd_caption_key_still_requests_sd_caption(
    monkeypatch, tmp_path, _fresh_static_config
) -> None:
    """W4: a fleet PV2_STATIC_CONFIG_DIR written before PUB-051 has no ``vision.sd_caption`` key.

    With SD prompts enabled, the vision user message must still request
    ``sd_caption`` via the shipped default text — otherwise every sidecar silently
    loses its SD prompt. An explicit ``sd_caption: null`` is an opt-out: no request.
    """
    from caption_pipeline_fakes import FakeOpenAI, openai_config, user_text

    from publisher_v2.config.static_loader import load_static_config

    shipped = (load_static_config(_PACKAGED_STATIC_DIR).ai_prompts.vision.sd_caption or "").strip()
    assert shipped and "sd_caption" in shipped, "setup: the packaged vision.sd_caption text is missing"

    async def _vision_user_message(vision: dict[str, Any], subdir: str) -> str:
        from publisher_v2.config.static_loader import get_static_config

        target = tmp_path / subdir
        target.mkdir()
        monkeypatch.setenv("PV2_STATIC_CONFIG_DIR", _write_custom_static_dir(target, vision))
        get_static_config.cache_clear()
        analyzer = VisionAnalyzerOpenAI(openai_config(sd_caption_enabled=True))
        fake = FakeOpenAI([])
        monkeypatch.setattr(analyzer, "client", fake)
        await analyzer.analyze("https://example.com/a.jpg")
        assert len(fake.vision_calls) == 1
        text = user_text(fake.vision_calls[0])
        assert _CUSTOM_VISION_USER in text, "setup: the custom static dir was not the one loaded"
        return text

    missing_key = await _vision_user_message({"system": "Custom analyst.", "user": _CUSTOM_VISION_USER}, "missing")
    assert "sd_caption" in missing_key, "a static dir without vision.sd_caption stopped requesting sd_caption"
    assert shipped in missing_key, "the missing key must fall back to the shipped default request text"

    opted_out = await _vision_user_message(
        {"system": "Custom analyst.", "user": _CUSTOM_VISION_USER, "sd_caption": None}, "null"
    )
    assert "sd_caption" not in opted_out, "an explicit sd_caption: null must opt out of the request"


async def test_senses_seed_hashing_runs_off_the_event_loop(monkeypatch) -> None:
    """Security (minor): hashing the image bytes for the senses seed is offloaded via ``asyncio.to_thread``.

    Structural: every function ``analyze`` hands to ``asyncio.to_thread`` is recorded,
    and ``senses_seed`` must be among them.
    """
    from caption_pipeline_fakes import FakeOpenAI, jpeg_bytes, openai_config

    import publisher_v2.services.ai as ai_mod

    offloaded: list[Any] = []
    real_to_thread = ai_mod.asyncio.to_thread

    async def _recording_to_thread(func, /, *args, **kwargs):
        offloaded.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(ai_mod.asyncio, "to_thread", _recording_to_thread)
    analyzer = VisionAnalyzerOpenAI(openai_config(vision_max_dimension=256))
    fake = FakeOpenAI([])
    monkeypatch.setattr(analyzer, "client", fake)

    await analyzer.analyze(jpeg_bytes(64, 48, (200, 30, 30)))

    assert fake.vision_calls, "setup: the analyzer made no vision call"
    assert ai_mod.senses_seed in offloaded, f"senses_seed ran on the event loop; offloaded: {offloaded}"
