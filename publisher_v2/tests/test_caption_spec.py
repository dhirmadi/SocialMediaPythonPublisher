"""Tests for CaptionSpec.for_platforms() (AC16, AC8). for_config was removed in #95."""

from __future__ import annotations

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    EmailConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.models import CaptionSpec


def _make_config(
    telegram: bool = False,
    instagram: bool = False,
    email: bool = False,
) -> ApplicationConfig:
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=telegram, instagram_enabled=instagram, email_enabled=email),
        telegram=None,
        instagram=None,
        email=EmailConfig(
            smtp_server="smtp.test",
            smtp_port=587,
            sender="f@t",
            recipient="t@t",
            password="p",
        )
        if email
        else None,
        content=ContentConfig(hashtag_string="#shibari #ropeart", archive=False, debug=False),
    )
    return cfg


class TestForPlatforms:
    """AC16: for_platforms returns dict[str, CaptionSpec] with entries only for enabled publishers."""

    def test_for_platforms_returns_enabled_only(self) -> None:
        cfg = _make_config(telegram=True, instagram=True, email=True)
        specs = CaptionSpec.for_platforms(cfg)
        assert isinstance(specs, dict)
        assert set(specs.keys()) == {"telegram", "instagram", "email"}
        for name, spec in specs.items():
            assert isinstance(spec, CaptionSpec)
            assert spec.platform == name

    def test_for_platforms_filters_disabled(self) -> None:
        cfg = _make_config(telegram=True, instagram=False, email=False)
        specs = CaptionSpec.for_platforms(cfg)
        assert set(specs.keys()) == {"telegram"}

    def test_for_platforms_no_publishers_returns_generic(self) -> None:
        cfg = _make_config(telegram=False, instagram=False, email=False)
        specs = CaptionSpec.for_platforms(cfg)
        # With no enabled publishers, should return at least a generic spec
        assert "generic" in specs

    def test_for_platforms_telegram_has_correct_limits(self) -> None:
        cfg = _make_config(telegram=True)
        specs = CaptionSpec.for_platforms(cfg)
        assert specs["telegram"].max_length == 4096

    def test_for_platforms_instagram_has_correct_limits(self) -> None:
        cfg = _make_config(instagram=True)
        specs = CaptionSpec.for_platforms(cfg)
        assert specs["instagram"].max_length == 2200

    def test_for_platforms_email_has_correct_limits(self) -> None:
        cfg = _make_config(email=True)
        specs = CaptionSpec.for_platforms(cfg)
        assert specs["email"].max_length == 240

    def test_platform_styles_loaded_from_yaml(self) -> None:
        """AC8: Platform style directives come from ai_prompts.yaml, not hardcoded."""
        cfg = _make_config(telegram=True, instagram=True, email=True)
        specs = CaptionSpec.for_platforms(cfg)
        # Styles should be non-empty strings loaded from config
        for spec in specs.values():
            assert spec.style
            assert isinstance(spec.style, str)
            assert len(spec.style) > 0


# --- #138: no hashtag instruction for platforms whose style has hashtags: false ---


def test_email_spec_has_smart_hashtags_off_even_when_feature_on() -> None:
    cfg = _make_config(telegram=True, instagram=True, email=True)
    assert cfg.features.smart_hashtags_enabled is True
    specs = CaptionSpec.for_platforms(cfg)
    assert specs["email"].smart_hashtags is False
    assert specs["telegram"].smart_hashtags is False
    assert specs["instagram"].smart_hashtags is True


def test_email_prompt_block_carries_no_hashtag_generation() -> None:
    from publisher_v2.services.ai import build_platform_block

    specs = CaptionSpec.for_platforms(_make_config(email=True))
    block = build_platform_block(1, "email", specs["email"])
    assert "Generate 3-8" not in block
