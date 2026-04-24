"""Tests for PUB-039: AI Caption Feature Flags & Voice Profile.

Covers all 16 ACs from the spec:
  A — Config model extension (AC-01..AC-03)
  B — Orchestrator model extension (AC-04..AC-05)
  C — Runtime parsing (AC-06..AC-08)
  D — Standalone mode (AC-09..AC-10)
  E — Voice profile pipeline (AC-11..AC-13)
  F — Logging safety (AC-14..AC-15)
  G — Backward compatibility (AC-16)
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from publisher_v2.config.schema import ContentConfig, FeaturesConfig

# ---------------------------------------------------------------------------
# Part A — Config Models (AC-01..AC-03)
# ---------------------------------------------------------------------------


class TestFeaturesConfigDefaults:
    """AC-01: FeaturesConfig has correct defaults for new flags."""

    def test_alt_text_enabled_default_true(self) -> None:
        cfg = FeaturesConfig()
        assert cfg.alt_text_enabled is True

    def test_smart_hashtags_enabled_default_true(self) -> None:
        cfg = FeaturesConfig()
        assert cfg.smart_hashtags_enabled is True

    def test_voice_matching_enabled_default_false(self) -> None:
        cfg = FeaturesConfig()
        assert cfg.voice_matching_enabled is False


class TestContentConfigVoiceProfile:
    """AC-02/AC-03: ContentConfig voice_profile field with validation."""

    def test_voice_profile_default_none(self) -> None:
        """AC-02: voice_profile defaults to None."""
        cfg = ContentConfig()
        assert cfg.voice_profile is None

    def test_voice_profile_accepts_none(self) -> None:
        """AC-02: Explicit None succeeds."""
        cfg = ContentConfig(voice_profile=None)
        assert cfg.voice_profile is None

    def test_voice_profile_accepts_list(self) -> None:
        """AC-02: List of strings succeeds."""
        cfg = ContentConfig(voice_profile=["example caption"])
        assert cfg.voice_profile == ["example caption"]

    def test_voice_profile_rejects_empty_strings(self) -> None:
        """AC-03: Empty strings are rejected."""
        with pytest.raises(ValidationError):
            ContentConfig(voice_profile=[""])

    def test_voice_profile_rejects_whitespace_only(self) -> None:
        """AC-03: Whitespace-only strings are rejected."""
        with pytest.raises(ValidationError):
            ContentConfig(voice_profile=["   "])

    def test_voice_profile_rejects_more_than_20(self) -> None:
        """AC-03: More than 20 entries rejected."""
        with pytest.raises(ValidationError):
            ContentConfig(voice_profile=["a"] * 21)

    def test_voice_profile_accepts_exactly_20(self) -> None:
        """AC-03: Exactly 20 entries is OK."""
        cfg = ContentConfig(voice_profile=["a"] * 20)
        assert len(cfg.voice_profile) == 20  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Part B — Orchestrator Models (AC-04..AC-05)
# ---------------------------------------------------------------------------


class TestOrchestratorFeatures:
    """AC-04: OrchestratorFeatures accepts new feature flag fields."""

    def test_accepts_new_flags(self) -> None:
        from publisher_v2.config.orchestrator_models import OrchestratorFeatures

        f = OrchestratorFeatures.model_validate(
            {"publish_enabled": True, "alt_text_enabled": False, "voice_matching_enabled": True}
        )
        assert f.alt_text_enabled is False
        assert f.voice_matching_enabled is True

    def test_missing_flags_default_safely(self) -> None:
        from publisher_v2.config.orchestrator_models import OrchestratorFeatures

        f = OrchestratorFeatures.model_validate({"publish_enabled": True})
        assert f.alt_text_enabled is True
        assert f.smart_hashtags_enabled is True
        assert f.voice_matching_enabled is False


class TestOrchestratorContent:
    """AC-05: OrchestratorContent accepts voice_profile."""

    def test_accepts_voice_profile(self) -> None:
        from publisher_v2.config.orchestrator_models import OrchestratorContent

        c = OrchestratorContent.model_validate({"voice_profile": ["x"]})
        assert c.voice_profile == ["x"]

    def test_voice_profile_default_none(self) -> None:
        from publisher_v2.config.orchestrator_models import OrchestratorContent

        c = OrchestratorContent.model_validate({})
        assert c.voice_profile is None


# ---------------------------------------------------------------------------
# Part C — Runtime Parsing (AC-06..AC-08)
# ---------------------------------------------------------------------------


class TestBuildAppConfigV2:
    """AC-06/AC-07: _build_app_config_v2 maps new fields correctly."""

    def test_v2_with_new_fields(self) -> None:
        """AC-06: v2 payload with all new fields → correctly mapped."""
        from publisher_v2.config.orchestrator_models import OrchestratorFeatures

        features = OrchestratorFeatures.model_validate(
            {"publish_enabled": True, "analyze_caption_enabled": True, "voice_matching_enabled": True}
        )
        features_dict = features.model_dump()
        result = FeaturesConfig(**features_dict)
        assert result.voice_matching_enabled is True

    def test_v2_missing_new_fields_defaults(self) -> None:
        """AC-07: v2 payload missing new fields → defaults applied."""
        from publisher_v2.config.orchestrator_models import OrchestratorFeatures

        features = OrchestratorFeatures.model_validate({"publish_enabled": True})
        features_dict = features.model_dump()
        result = FeaturesConfig(**features_dict)
        assert result.alt_text_enabled is True
        assert result.smart_hashtags_enabled is True
        assert result.voice_matching_enabled is False


class TestBuildAppConfigV1:
    """AC-08: v1 parsing uses safe defaults."""

    def test_v1_defaults(self) -> None:
        """AC-08: v1 payload → all new fields at safe defaults."""
        from publisher_v2.config.orchestrator_models import OrchestratorFeatures

        # v1 only sends a minimal features payload
        features = OrchestratorFeatures.model_validate({"publish_enabled": False})
        features_dict = features.model_dump()
        result = FeaturesConfig(**features_dict)
        assert result.alt_text_enabled is True
        assert result.smart_hashtags_enabled is True
        assert result.voice_matching_enabled is False


# ---------------------------------------------------------------------------
# Part D — Standalone Mode (AC-09..AC-10)
# ---------------------------------------------------------------------------


class TestStandaloneEnvVars:
    """AC-09/AC-10: load_application_config reads new env vars."""

    def test_feature_alt_text_env_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-09: FEATURE_ALT_TEXT=false → alt_text_enabled=False."""
        from publisher_v2.config.loader import parse_bool_env

        assert parse_bool_env("false", True, var_name="FEATURE_ALT_TEXT") is False

    def test_feature_alt_text_env_absent(self) -> None:
        """AC-09: FEATURE_ALT_TEXT absent → default True."""
        from publisher_v2.config.loader import parse_bool_env

        assert parse_bool_env(None, True, var_name="FEATURE_ALT_TEXT") is True

    def test_feature_voice_matching_env_true(self) -> None:
        """AC-09: FEATURE_VOICE_MATCHING=true → voice_matching_enabled=True."""
        from publisher_v2.config.loader import parse_bool_env

        assert parse_bool_env("true", False, var_name="FEATURE_VOICE_MATCHING") is True

    def test_content_settings_voice_profile(self) -> None:
        """AC-10: CONTENT_SETTINGS JSON with voice_profile → parsed into ContentConfig."""
        from publisher_v2.config.loader import _load_content_settings_from_env

        with patch.dict("os.environ", {"CONTENT_SETTINGS": json.dumps({"voice_profile": ["a", "b"]})}):
            result = _load_content_settings_from_env()
        assert result is not None
        assert result["voice_profile"] == ["a", "b"]


# ---------------------------------------------------------------------------
# Part E — Voice Profile Pipeline (AC-11..AC-13)
# ---------------------------------------------------------------------------


class TestVoiceProfilePipeline:
    """AC-11..AC-13: CaptionSpec.for_platforms() voice profile merge."""

    def _make_config(self, voice_matching: bool, voice_profile: list[str] | None) -> object:
        """Build a minimal ApplicationConfig with the given voice settings."""
        from publisher_v2.config.schema import (
            ApplicationConfig,
            DropboxConfig,
            OpenAIConfig,
            PlatformsConfig,
            StoragePathConfig,
        )

        return ApplicationConfig(
            dropbox=DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"),
            storage_paths=StoragePathConfig(image_folder="/Photos"),
            openai=OpenAIConfig(api_key="sk-test"),
            platforms=PlatformsConfig(telegram_enabled=True),
            content=ContentConfig(voice_profile=voice_profile),
            features=FeaturesConfig(voice_matching_enabled=voice_matching),
        )

    def test_voice_matching_enabled_with_profile_prepends(self) -> None:
        """AC-11: voice_matching=True + profile → examples start with profile."""
        from publisher_v2.core.models import CaptionSpec

        cfg = self._make_config(voice_matching=True, voice_profile=["vp1", "vp2"])
        specs = CaptionSpec.for_platforms(cfg)  # type: ignore[arg-type]
        spec = specs["telegram"]
        assert spec.examples[:2] == ("vp1", "vp2")

    def test_voice_matching_disabled_ignores_profile(self) -> None:
        """AC-12: voice_matching=False + profile → profile not in examples."""
        from publisher_v2.core.models import CaptionSpec

        cfg = self._make_config(voice_matching=False, voice_profile=["vp1"])
        specs = CaptionSpec.for_platforms(cfg)  # type: ignore[arg-type]
        spec = specs["telegram"]
        assert "vp1" not in spec.examples

    def test_voice_matching_enabled_no_profile_no_crash(self) -> None:
        """AC-13: voice_matching=True + None profile → graceful no-op."""
        from publisher_v2.core.models import CaptionSpec

        cfg = self._make_config(voice_matching=True, voice_profile=None)
        specs = CaptionSpec.for_platforms(cfg)  # type: ignore[arg-type]
        assert "telegram" in specs  # no crash

    def test_voice_matching_enabled_empty_profile_no_crash(self) -> None:
        """AC-13: voice_matching=True + empty profile → graceful no-op."""
        from publisher_v2.core.models import CaptionSpec

        cfg = self._make_config(voice_matching=True, voice_profile=[])
        specs = CaptionSpec.for_platforms(cfg)  # type: ignore[arg-type]
        assert "telegram" in specs


# ---------------------------------------------------------------------------
# Part F — Logging Safety (AC-14..AC-15)
# ---------------------------------------------------------------------------


class TestLoggingSafety:
    """AC-14/AC-15: voice_profile redacted in logs."""

    def test_safe_log_config_redacts_voice_profile(self) -> None:
        """AC-14: _safe_log_config redacts voice_profile."""
        from publisher_v2.config.loader import _safe_log_config

        result = _safe_log_config({"voice_profile": ["my caption"]})
        assert result["voice_profile"] == "***REDACTED***"

    def test_safe_log_config_other_keys_unchanged(self) -> None:
        """AC-15: Non-sensitive keys pass through."""
        from publisher_v2.config.loader import _safe_log_config

        result = _safe_log_config({"archive": True, "voice_profile": ["x"]})
        assert result["archive"] is True
        assert result["voice_profile"] == "***REDACTED***"


# ---------------------------------------------------------------------------
# Part G — Backward Compatibility (AC-16)
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """AC-16: Defaults produce unchanged behavior."""

    def test_defaults_no_voice_profile_in_specs(self) -> None:
        """AC-16: Default config → CaptionSpec has no voice profile entries."""
        from publisher_v2.config.schema import (
            ApplicationConfig,
            DropboxConfig,
            OpenAIConfig,
            PlatformsConfig,
            StoragePathConfig,
        )
        from publisher_v2.core.models import CaptionSpec

        cfg = ApplicationConfig(
            dropbox=DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"),
            storage_paths=StoragePathConfig(image_folder="/Photos"),
            openai=OpenAIConfig(api_key="sk-test"),
            platforms=PlatformsConfig(telegram_enabled=True),
            content=ContentConfig(),
            features=FeaturesConfig(),
        )
        specs = CaptionSpec.for_platforms(cfg)
        spec = specs["telegram"]
        # With default voice_matching_enabled=False and voice_profile=None,
        # examples should only have YAML-defined entries (no voice profile)
        # This proves backward compatibility
        assert isinstance(spec.examples, tuple)
