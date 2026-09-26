"""PUB-050 AC4 (#190): the cron caption prompt carries the *sampled* corpus, not all of it.

Everything below the external boundaries is real: the real ``OrchestratorConfigSource``
parses a runtime payload served over ``httpx.MockTransport``, the real ``DropboxStorage``
runs against a faked Dropbox SDK client, and the real ``WorkflowOrchestrator`` +
``AIService`` build the prompt that a faked OpenAI client records.

The assertion is deliberately expressed against ``sample_voice_examples`` itself: the
prompt must contain exactly what the sampler returns for *this run's* seed
(``selected_content_hash or selected_hash``) and platform set — a workflow that keeps
calling ``truncate_voice_profile_to_budget`` ships the whole profile and fails here.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import dropbox
import httpx
import pytest
from caption_pipeline_fakes import FakeOpenAI
from PIL import Image

from publisher_v2.config.orchestrator_client import OrchestratorClient
from publisher_v2.config.source import OrchestratorConfigSource
from publisher_v2.services.ai import sample_voice_examples

IMAGE_FOLDER = "/Photos"
IMAGE_NAME = "img.jpg"
# Fixture credentials. Spelled out as obvious fakes so that neither a human
# reviewer nor a secret scanner can mistake them for real material.
FAKE_SERVICE_TOKEN = "fake-orchestrator-service-token-for-tests"  # pragma: allowlist secret
FAKE_DROPBOX_REFRESH_TOKEN = "fake-dropbox-refresh-token-for-tests"  # pragma: allowlist secret

# Pinned so the test knows the exact seed the workflow will use: the selection
# path takes the storage entry's content_hash as `selected_content_hash`. Shaped
# like a Dropbox content hash (64 hex chars) but visibly a repeating fixture
# pattern, not a digest of anything.
CONTENT_HASH = "deadbeef" * 8

PROFILE: list[str] = [f"Owner line number {i}." for i in range(1, 13)]
TELEGRAM_TAGGED: list[str] = PROFILE[:3]
EMAIL_TAGGED: list[str] = PROFILE[3:6]

HOST = "xxx.shibari.photo"

# Every platform key a caption completion may be asked for. The shared fake
# answers with all of them; `_parse_platform_captions` reads only the enabled ones.
CAPTION_PLATFORMS = ["telegram", "email", "instagram", "generic"]


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 80, 60)).save(buf, format="JPEG")
    return buf.getvalue()


class _FakeDropbox:
    """In-memory stand-in for ``dropbox.Dropbox`` (the SDK client boundary)."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.files: dict[str, bytes] = {f"{IMAGE_FOLDER}/{IMAGE_NAME}": _jpeg()}

    def files_list_folder(self, path: str) -> SimpleNamespace:
        entries = [
            dropbox.files.FileMetadata(name=p.rsplit("/", 1)[1], path_lower=p.lower(), content_hash=CONTENT_HASH)
            for p in self.files
            if p.rsplit("/", 1)[0] == path
        ]
        return SimpleNamespace(entries=entries, has_more=False, cursor=None)

    def files_download(self, path: str) -> tuple[None, SimpleNamespace]:
        return None, SimpleNamespace(content=self.files[path])

    def files_upload(self, data: bytes, path: str, **_kwargs: Any) -> None:
        self.files[path] = data

    def files_get_temporary_link(self, path: str) -> SimpleNamespace:
        return SimpleNamespace(link=f"https://dl.example/{path}")

    def files_get_metadata(self, path: str) -> dropbox.files.FileMetadata:
        return dropbox.files.FileMetadata(name=path.rsplit("/", 1)[1], id="id:1", rev="0123456789", size=1)

    def files_create_folder_v2(self, _path: str) -> None:
        return None

    def files_move_v2(self, src: str, dst: str, **_kwargs: Any) -> None:
        if src in self.files:
            self.files[dst] = self.files.pop(src)


def _source(config: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> OrchestratorConfigSource:
    """Real ``OrchestratorConfigSource`` over a mocked orchestrator HTTP API."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host":
            return httpx.Response(
                200,
                json={
                    "schema_version": 2,
                    "tenant": "xxx",
                    "app_type": "publisher_v2",
                    "config_version": "v",
                    "ttl_seconds": 600,
                    "config": config,
                },
            )
        if request.url.path == "/v1/credentials/resolve":
            return httpx.Response(
                200, json={"provider": "dropbox", "version": "v1", "refresh_token": FAKE_DROPBOX_REFRESH_TOKEN}
            )
        return httpx.Response(500, json={"error": "unexpected"})

    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", FAKE_SERVICE_TOKEN)
    monkeypatch.setenv("ORCHESTRATOR_BASE_DOMAIN", "shibari.photo")
    monkeypatch.setenv("DROPBOX_APP_KEY", "fake-dropbox-app-key-for-tests")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "fake-dropbox-app-secret-for-tests")  # pragma: allowlist secret
    src = OrchestratorConfigSource()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://orch.test")
    src._client = OrchestratorClient(  # type: ignore[attr-defined]
        base_url="https://orch.test", service_token=FAKE_SERVICE_TOKEN, prefer_post=True, client=client
    )
    return src


def _payload(publishers: list[dict[str, Any]], content: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "features": {"publish_enabled": True, "analyze_caption_enabled": True},
        "storage": {
            "provider": "dropbox",
            "credentials_ref": "fake-dropbox-credentials-ref",
            "paths": {"root": IMAGE_FOLDER},
        },
        "publishers": publishers,
        "ai": {"credentials_ref": "fake-openai-credentials-ref"},
        "content": content,
    }
    if any(p["type"] in ("fetlife", "email") for p in publishers):
        payload["email_server"] = {
            "host": "smtp.example",
            "port": 587,
            "from_email": "bot@example.com",
            "password_ref": "fake-smtp-password-ref",  # pragma: allowlist secret
        }
    return payload


TELEGRAM_PUBLISHER = {"id": "tg", "type": "telegram", "config": {"channel_id": "@chan"}}
EMAIL_PUBLISHER = {"id": "em", "type": "fetlife", "config": {"recipient": "fl@example.com"}}


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[None]:
    """Posted-state files live under HOME; keep them out of the developer's real one."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    yield


@pytest.fixture
def fake_openai() -> FakeOpenAI:
    # PUB-051 AC4/AC5: vision replies carry `sd_caption`; the JSON-mode caption call gets platform keys only.
    return FakeOpenAI(CAPTION_PLATFORMS)


async def _run(
    publishers: list[dict[str, Any]], content: dict[str, Any], monkeypatch: pytest.MonkeyPatch, fake: FakeOpenAI
) -> Any:
    """Run one real dry publish and return the resolved config (for the platform set)."""
    from publisher_v2.core.workflow import WorkflowOrchestrator
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
    from publisher_v2.services.storage_factory import create_storage

    src = _source(_payload(publishers, content), monkeypatch)
    rc = await src.get_config(HOST)
    cfg = rc.config
    assert cfg.features.voice_matching_enabled is True, "a profile in the payload must switch voice matching on"

    with (
        patch("publisher_v2.services.storage.dropbox.Dropbox", _FakeDropbox),
        patch("publisher_v2.services.ai.AsyncOpenAI", lambda *_a, **_kw: fake),
    ):
        storage = create_storage(cfg)
        ai_service = AIService(VisionAnalyzerOpenAI(cfg.openai), CaptionGeneratorOpenAI(cfg.openai))
        orchestrator = WorkflowOrchestrator(cfg, storage, ai_service, [])
        result = await orchestrator.execute(select_filename=IMAGE_NAME, dry_publish=True)
        await ai_service.aclose()

    assert result.error is None, result.error
    # Fail loudly if the fake never saw the multi-platform caption call, rather
    # than letting a stale fake read as a sampler bug.
    assert fake.caption_calls, "the fake never saw the multi-platform caption call"
    assert all(c.get("response_format") == {"type": "json_object"} for c in fake.caption_calls), (
        "the caption call is no longer JSON mode; the shared fake's routing is stale"
    )
    return cfg


def _voice_block_examples(fake: FakeOpenAI) -> list[str]:
    """The numbered lines of the STYLE REFERENCES block the caption call carried."""
    for call in fake.caption_calls:
        for message in call.get("messages") or []:
            content = message.get("content")
            if isinstance(content, str) and "BEGIN VOICE EXAMPLES" in content:
                body = content.split("BEGIN VOICE EXAMPLES", 1)[1].split("END VOICE EXAMPLES", 1)[0]
                return [line.split(". ", 1)[1] for line in body.strip().splitlines() if ". " in line]
    raise AssertionError("no STYLE REFERENCES block reached the OpenAI caption call")


async def test_workflow_run_prompt_contains_sampled_voice_examples(
    monkeypatch: pytest.MonkeyPatch, fake_openai: FakeOpenAI
) -> None:
    """Untagged corpus: the prompt carries this image's sample, not the whole profile."""
    await _run([TELEGRAM_PUBLISHER], {"voice_profile": PROFILE, "archive": False}, monkeypatch, fake_openai)

    sent = _voice_block_examples(fake_openai)
    expected = sample_voice_examples(PROFILE, seed_source=CONTENT_HASH, platform_tags=None, platforms=["telegram"])

    assert sent == expected, "the prompt did not carry the per-image sample for this run's seed"
    assert len(sent) < len(PROFILE), "the full profile reached the prompt; nothing was sampled"


async def test_workflow_run_prompt_prefers_tagged_examples_when_voice_profile_tags_set(
    monkeypatch: pytest.MonkeyPatch,
    fake_openai: FakeOpenAI,
) -> None:
    """Single enabled platform with tags: only that platform's tagged lines are eligible."""
    tags = {"telegram": PROFILE[:6], "email": EMAIL_TAGGED}
    await _run(
        [TELEGRAM_PUBLISHER],
        {"voice_profile": PROFILE, "voice_profile_tags": tags, "archive": False},
        monkeypatch,
        fake_openai,
    )

    sent = _voice_block_examples(fake_openai)
    expected = sample_voice_examples(PROFILE, seed_source=CONTENT_HASH, platform_tags=tags, platforms=["telegram"])

    assert sent == expected
    assert set(sent) <= set(PROFILE[:6]), f"an untagged example was sent for a telegram-only tenant: {sent}"


async def test_workflow_run_prompt_unions_tags_when_two_platforms_enabled(
    monkeypatch: pytest.MonkeyPatch, fake_openai: FakeOpenAI
) -> None:
    """Two enabled platforms, disjoint tags: one shared prompt prefers the union of both."""
    tags = {"telegram": TELEGRAM_TAGGED, "email": EMAIL_TAGGED}
    cfg = await _run(
        [TELEGRAM_PUBLISHER, EMAIL_PUBLISHER],
        {"voice_profile": PROFILE, "voice_profile_tags": tags, "archive": False},
        monkeypatch,
        fake_openai,
    )
    assert cfg.platforms.telegram_enabled and cfg.platforms.email_enabled, "both platforms must be enabled"

    sent = _voice_block_examples(fake_openai)
    expected = sample_voice_examples(
        PROFILE, seed_source=CONTENT_HASH, platform_tags=tags, platforms=["telegram", "email"]
    )

    assert sent == expected
    union = set(TELEGRAM_TAGGED) | set(EMAIL_TAGGED)
    assert set(sent) <= union, f"an untagged example beat the tagged union: {sent}"
    assert set(sent) & set(TELEGRAM_TAGGED), "the union dropped the telegram-tagged half"
    assert set(sent) & set(EMAIL_TAGGED), "the union dropped the email-tagged half"
