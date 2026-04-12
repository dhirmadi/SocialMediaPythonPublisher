"""Regression test for stale orchestrator publisher list bug.

When a non-publish operation (delete, keep, remove) triggers
_ensure_orchestrator() before _ensure_publishers() resolves credentials,
the cached orchestrator holds a stale publisher list where email (or other)
publishers are disabled due to unresolved passwords.

Subsequent publish calls must sync the orchestrator's publisher list
with the freshly-resolved list from _ensure_publishers().

See: lbd.shibari.photo production incident 2026-03-10
"""

from __future__ import annotations

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    EmailConfig,
    FeaturesConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.models import PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.web.service import WebImageService


class _StubPublisher(Publisher):
    """Publisher that tracks calls and reports as enabled."""

    def __init__(self, name: str = "stub", *, enabled: bool = True) -> None:
        self._name = name
        self._enabled = enabled
        self.publish_calls: list[tuple[str, str]] = []

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        self.publish_calls.append((image_path, caption))
        return PublishResult(success=True, platform=self._name, post_id="ok")


class _DummyStorage:
    async def list_images(self, folder: str) -> list[str]:
        return ["test.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"image-bytes"

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return f"https://example.com/{filename}"

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        pass

    async def get_file_metadata(self, folder: str, filename: str) -> dict[str, str]:
        return {"id": "id", "rev": "rev"}

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        return None

    async def delete_image(self, folder: str, filename: str) -> None:
        pass


class _DummyAI:
    class _Analyzer:
        async def analyze(self, url_or_bytes):
            from publisher_v2.core.models import ImageAnalysis

            return ImageAnalysis(description="d", mood="m", tags=["t"], nsfw=False, safety_labels=[])

    class _Generator:
        sd_caption_model = "test"

        async def generate(self, analysis, spec):
            return "caption"

        async def generate_with_sd(self, analysis, spec):
            return {"caption": "caption", "sd_caption": None}

    def __init__(self):
        self.analyzer = self._Analyzer()
        self.generator = self._Generator()

    async def create_caption_pair_from_analysis(self, analysis, spec):
        return "caption", None


def _make_config(*, email_password: str | None = None) -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k",
            app_secret="s",
            refresh_token="r",
            image_folder="/Photos",
            archive_folder="archive",
            folder_keep="keep",
            folder_remove="remove",
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=True),
        features=FeaturesConfig(
            publish_enabled=True,
            delete_enabled=True,
            analyze_caption_enabled=False,
        ),
        email=EmailConfig(
            sender="test@example.com",
            recipient="dest@example.com",
            password=email_password,
            smtp_server="smtp.example.com",
            smtp_port=587,
        ),
        content=ContentConfig(hashtag_string="", archive=False, debug=False),
    )


def _make_service(monkeypatch: pytest.MonkeyPatch, *, email_password: str | None = None) -> WebImageService:
    cfg = _make_config(email_password=email_password)
    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: cfg,
    )
    svc = WebImageService()
    svc.storage = _DummyStorage()  # type: ignore[assignment]
    svc.ai_service = _DummyAI()  # type: ignore[assignment]
    return svc


@pytest.mark.asyncio
async def test_ensure_orchestrator_syncs_publisher_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the orchestrator is cached, _ensure_orchestrator must update its publisher list.

    Scenario: delete_image creates the orchestrator with stale (disabled) publishers.
    Then _ensure_publishers resolves credentials and rebuilds the publisher list.
    _ensure_orchestrator must propagate the new list to the cached orchestrator.
    """
    svc = _make_service(monkeypatch, email_password=None)

    # EmailPublisher starts disabled because password=None
    email_pubs = [p for p in svc.publishers if p.platform_name == "email"]
    assert len(email_pubs) == 1
    assert not email_pubs[0].is_enabled(), "EmailPublisher should be disabled without password"

    # Simulate delete_image creating and caching the orchestrator with disabled publishers
    svc.orchestrator = WorkflowOrchestrator(
        svc.config,
        svc.storage,
        svc.ai_service,  # type: ignore[arg-type]
        list(svc.publishers),  # type: ignore[arg-type]
    )
    stale_orchestrator = svc.orchestrator

    # Now simulate what _ensure_publishers does: resolve the password and rebuild
    new_email = svc.config.email.model_copy(update={"password": "resolved-password"})  # type: ignore[union-attr]
    svc.config = svc.config.model_copy(update={"email": new_email})
    from publisher_v2.services.publishers import build_publishers

    svc.publishers = build_publishers(svc.config)

    # Verify the new publisher list has an enabled email publisher
    new_email_pubs = [p for p in svc.publishers if p.platform_name == "email"]
    assert new_email_pubs[0].is_enabled(), "EmailPublisher should be enabled after password resolution"

    # Call _ensure_orchestrator -- it should sync the publisher list
    orchestrator = await svc._ensure_orchestrator()

    # Must be the same cached instance (no unnecessary recreation)
    assert orchestrator is stale_orchestrator

    # The orchestrator's publishers must be the updated list
    orch_email_pubs = [p for p in orchestrator.publishers if p.platform_name == "email"]
    assert len(orch_email_pubs) == 1
    assert orch_email_pubs[0].is_enabled(), "Orchestrator must use the updated publisher list after _ensure_publishers"


@pytest.mark.asyncio
async def test_delete_then_publish_uses_resolved_publishers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: delete creates stale orchestrator, then publish must still work.

    This reproduces the production bug where lbd.shibari.photo publish returned
    any_success=false because the orchestrator held disabled publishers from
    a prior delete operation.
    """
    cfg = _make_config(email_password="valid-password")
    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: cfg,
    )
    svc = WebImageService()
    svc.storage = _DummyStorage()  # type: ignore[assignment]
    svc.ai_service = _DummyAI()  # type: ignore[assignment]

    # Step 1: create the orchestrator the same way delete_image would
    orchestrator = await svc._ensure_orchestrator()
    assert svc.orchestrator is not None, "orchestrator should be cached"

    # Step 2: swap in a new publisher list (simulating _ensure_publishers rebuilding)
    stub = _StubPublisher("email", enabled=True)
    svc.publishers = [stub]

    # Step 3: _ensure_orchestrator should sync the publisher list
    orchestrator = await svc._ensure_orchestrator()
    assert stub in orchestrator.publishers, "Orchestrator must use the freshly-resolved publisher list"
