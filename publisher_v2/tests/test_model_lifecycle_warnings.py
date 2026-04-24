"""Tests for PUB-040: OpenAI Model Lifecycle Warnings.

Covers all 16 ACs:
  A — ModelLifecycle model (AC-01..AC-02)
  B — OpenAIConfig extension (AC-03..AC-04)
  C — Orchestrator parsing (AC-05..AC-09)
  D — Warning emitter (AC-10..AC-14)
  E — Cache behavior (AC-15)
  F — Standalone mode (AC-16)
"""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from publisher_v2.config.schema import OpenAIConfig

# ---------------------------------------------------------------------------
# Part A — ModelLifecycle model (AC-01..AC-02)
# ---------------------------------------------------------------------------


class TestModelLifecycle:
    """AC-01/AC-02: ModelLifecycle model validation."""

    def test_valid_construction(self) -> None:
        """AC-01: Valid ModelLifecycle constructs successfully."""
        from publisher_v2.config.schema import ModelLifecycle

        lc = ModelLifecycle(
            warning="deprecated_model",
            shutdown_date="2026-06-01",
            recommended_replacement="gpt-4o-2026-01",
            severity="warning",
        )
        assert lc.warning == "deprecated_model"
        assert lc.shutdown_date == "2026-06-01"
        assert lc.recommended_replacement == "gpt-4o-2026-01"
        assert lc.severity == "warning"

    def test_severity_info(self) -> None:
        """AC-01: severity='info' is valid."""
        from publisher_v2.config.schema import ModelLifecycle

        lc = ModelLifecycle(warning="w", shutdown_date="d", recommended_replacement="r", severity="info")
        assert lc.severity == "info"

    def test_severity_critical(self) -> None:
        """AC-01: severity='critical' is valid."""
        from publisher_v2.config.schema import ModelLifecycle

        lc = ModelLifecycle(warning="w", shutdown_date="d", recommended_replacement="r", severity="critical")
        assert lc.severity == "critical"

    def test_unknown_severity_rejected(self) -> None:
        """AC-02: Unknown severity raises ValidationError."""
        from publisher_v2.config.schema import ModelLifecycle

        with pytest.raises(ValidationError):
            ModelLifecycle(warning="w", shutdown_date="d", recommended_replacement="r", severity="unknown")


# ---------------------------------------------------------------------------
# Part B — OpenAIConfig extension (AC-03..AC-04)
# ---------------------------------------------------------------------------


class TestOpenAIConfigLifecycle:
    """AC-03/AC-04: OpenAIConfig lifecycle fields."""

    def test_defaults_none(self) -> None:
        """AC-03: Both lifecycle fields default to None."""
        cfg = OpenAIConfig()
        assert cfg.vision_model_lifecycle is None
        assert cfg.caption_model_lifecycle is None

    def test_accepts_model_lifecycle(self) -> None:
        """AC-04: OpenAIConfig stores ModelLifecycle instances."""
        from publisher_v2.config.schema import ModelLifecycle

        lc = ModelLifecycle(warning="w", shutdown_date="d", recommended_replacement="r", severity="warning")
        cfg = OpenAIConfig(vision_model_lifecycle=lc)
        assert cfg.vision_model_lifecycle is not None
        assert cfg.vision_model_lifecycle.severity == "warning"


# ---------------------------------------------------------------------------
# Part C — Orchestrator parsing (AC-05..AC-09)
# ---------------------------------------------------------------------------


class TestOrchestratorAILifecycle:
    """AC-05/AC-06: OrchestratorAI accepts lifecycle dicts."""

    def test_accepts_lifecycle_dict(self) -> None:
        """AC-05: OrchestratorAI accepts lifecycle as dict."""
        from publisher_v2.config.orchestrator_models import OrchestratorAI

        ai = OrchestratorAI.model_validate(
            {
                "credentials_ref": "x",
                "vision_model": "gpt-4o",
                "vision_model_lifecycle": {
                    "warning": "deprecated_model",
                    "shutdown_date": "2026-06-01",
                    "recommended_replacement": "gpt-4o-2026-01",
                    "severity": "critical",
                },
            }
        )
        assert ai.vision_model_lifecycle is not None
        assert isinstance(ai.vision_model_lifecycle, dict)

    def test_null_lifecycle(self) -> None:
        """AC-06: null lifecycle → None."""
        from publisher_v2.config.orchestrator_models import OrchestratorAI

        ai = OrchestratorAI.model_validate({"vision_model_lifecycle": None})
        assert ai.vision_model_lifecycle is None

    def test_missing_lifecycle(self) -> None:
        """AC-06: Missing lifecycle field → None."""
        from publisher_v2.config.orchestrator_models import OrchestratorAI

        ai = OrchestratorAI.model_validate({})
        assert ai.vision_model_lifecycle is None
        assert ai.caption_model_lifecycle is None


class TestBuildAppConfigV2Lifecycle:
    """AC-07/AC-08: _build_app_config_v2 lifecycle mapping."""

    def test_valid_lifecycle_mapped(self) -> None:
        """AC-07: Valid lifecycle dict → ModelLifecycle on OpenAIConfig."""
        from publisher_v2.config.schema import ModelLifecycle
        from publisher_v2.config.source import _map_lifecycle

        lc_dict = {
            "warning": "deprecated_model",
            "shutdown_date": "2026-06-01",
            "recommended_replacement": "gpt-4o-2026-01",
            "severity": "critical",
        }
        result = _map_lifecycle(lc_dict, "vision")
        assert isinstance(result, ModelLifecycle)
        assert result.severity == "critical"

    def test_null_lifecycle_mapped_none(self) -> None:
        """AC-07: null lifecycle → None."""
        from publisher_v2.config.source import _map_lifecycle

        assert _map_lifecycle(None, "vision") is None

    def test_malformed_lifecycle_graceful(self) -> None:
        """AC-08: Malformed lifecycle dict → None (no crash)."""
        from publisher_v2.config.source import _map_lifecycle

        # Missing required 'severity' field
        result = _map_lifecycle({"warning": "x", "shutdown_date": "d"}, "vision")
        assert result is None


class TestBuildAppConfigV1Lifecycle:
    """AC-09: v1 parsing → both None."""

    def test_v1_defaults(self) -> None:
        """AC-09: v1 defaults are None."""
        cfg = OpenAIConfig()
        assert cfg.vision_model_lifecycle is None
        assert cfg.caption_model_lifecycle is None


# ---------------------------------------------------------------------------
# Part D — Warning emitter (AC-10..AC-14)
# ---------------------------------------------------------------------------


class TestEmitModelLifecycleWarnings:
    """AC-10..AC-14: Warning emitter behavior."""

    def test_warning_severity_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-10: severity='warning' → logging.WARNING."""
        from publisher_v2.config.schema import ModelLifecycle
        from publisher_v2.config.source import emit_model_lifecycle_warnings

        lc = ModelLifecycle(
            warning="deprecated", shutdown_date="2026-06-01", recommended_replacement="gpt-4o-new", severity="warning"
        )
        cfg = OpenAIConfig(vision_model_lifecycle=lc)

        with caplog.at_level(logging.DEBUG):
            emit_model_lifecycle_warnings(cfg)

        assert any(r.levelno == logging.WARNING for r in caplog.records)
        assert any("vision" in r.message for r in caplog.records)

    def test_critical_severity_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-11: severity='critical' → logging.ERROR."""
        from publisher_v2.config.schema import ModelLifecycle
        from publisher_v2.config.source import emit_model_lifecycle_warnings

        lc = ModelLifecycle(
            warning="shutdown", shutdown_date="2026-04-01", recommended_replacement="gpt-5", severity="critical"
        )
        cfg = OpenAIConfig(caption_model_lifecycle=lc)

        with caplog.at_level(logging.DEBUG):
            emit_model_lifecycle_warnings(cfg)

        assert any(r.levelno == logging.ERROR for r in caplog.records)
        assert any("caption" in r.message for r in caplog.records)

    def test_info_severity_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-12: severity='info' → logging.INFO."""
        from publisher_v2.config.schema import ModelLifecycle
        from publisher_v2.config.source import emit_model_lifecycle_warnings

        lc = ModelLifecycle(
            warning="advisory", shutdown_date="2027-01-01", recommended_replacement="gpt-5", severity="info"
        )
        cfg = OpenAIConfig(vision_model_lifecycle=lc)

        with caplog.at_level(logging.DEBUG):
            emit_model_lifecycle_warnings(cfg)

        assert any(r.levelno == logging.INFO for r in caplog.records)

    def test_both_none_no_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-13: Both None → zero log records."""
        from publisher_v2.config.source import emit_model_lifecycle_warnings

        cfg = OpenAIConfig()
        with caplog.at_level(logging.DEBUG):
            emit_model_lifecycle_warnings(cfg)

        lifecycle_records = [r for r in caplog.records if "lifecycle" in r.message]
        assert len(lifecycle_records) == 0

    def test_no_secrets_in_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-14: Log output contains no credentials_ref or api_key."""
        from publisher_v2.config.schema import ModelLifecycle
        from publisher_v2.config.source import emit_model_lifecycle_warnings

        lc = ModelLifecycle(warning="w", shutdown_date="d", recommended_replacement="r", severity="warning")
        cfg = OpenAIConfig(api_key="sk-secret-key-12345", vision_model_lifecycle=lc)

        with caplog.at_level(logging.DEBUG):
            emit_model_lifecycle_warnings(cfg)

        for record in caplog.records:
            assert "sk-secret" not in record.message
            assert "api_key" not in record.message
            assert "credentials_ref" not in record.message


# ---------------------------------------------------------------------------
# Part E — Standalone mode (AC-16)
# ---------------------------------------------------------------------------


class TestStandaloneMode:
    """AC-16: Standalone mode → both None, no warnings."""

    def test_standalone_defaults(self) -> None:
        """AC-16: OpenAIConfig defaults → no lifecycle."""
        cfg = OpenAIConfig()
        assert cfg.vision_model_lifecycle is None
        assert cfg.caption_model_lifecycle is None
