import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.config.static_loader import (
    AICaptionPrompts,
    AISDCaptionPrompts,
    AIPromptsConfig,
    StaticConfig,
)
from publisher_v2.services.ai import CaptionGeneratorOpenAI


def _static_cfg(
    caption_system: str | None = None,
    caption_role: str | None = None,
    sd_system: str | None = None,
    sd_role: str | None = None,
) -> StaticConfig:
    return StaticConfig(
        ai_prompts=AIPromptsConfig(
            caption=AICaptionPrompts(system=caption_system, role=caption_role),
            sd_caption=AISDCaptionPrompts(system=sd_system, role=sd_role),
        )
    )


def test_orchestrator_prompts_take_precedence_over_static_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Regression for Issue #48: static YAML prompts must not overwrite tenant-specific
    prompts delivered via orchestrator config.
    """
    monkeypatch.setattr(
        "publisher_v2.services.ai.get_static_config",
        lambda: _static_cfg(
            caption_system="STATIC_SYSTEM",
            caption_role="STATIC_ROLE",
            sd_system="STATIC_SD_SYSTEM",
            sd_role="STATIC_SD_ROLE",
        ),
    )

    cfg = OpenAIConfig(
        api_key="sk-test",
        system_prompt="TENANT_SYSTEM",
        role_prompt="TENANT_ROLE",
        sd_caption_system_prompt="TENANT_SD_SYSTEM",
        sd_caption_role_prompt="TENANT_SD_ROLE",
    )
    gen = CaptionGeneratorOpenAI(cfg)

    assert gen.system_prompt == "TENANT_SYSTEM"
    assert gen.role_prompt == "TENANT_ROLE"
    assert gen.sd_caption_system_prompt == "TENANT_SD_SYSTEM"
    assert gen.sd_caption_role_prompt == "TENANT_SD_ROLE"


def test_static_yaml_is_used_as_fallback_when_config_is_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When config uses schema defaults (i.e., orchestrator didn't provide custom prompts),
    static YAML should be applied as fallback.
    """
    monkeypatch.setattr(
        "publisher_v2.services.ai.get_static_config",
        lambda: _static_cfg(
            caption_system="STATIC_SYSTEM",
            caption_role="STATIC_ROLE",
            sd_system="STATIC_SD_SYSTEM",
            sd_role="STATIC_SD_ROLE",
        ),
    )

    cfg = OpenAIConfig(api_key="sk-test")  # uses schema defaults for prompts
    gen = CaptionGeneratorOpenAI(cfg)

    assert gen.system_prompt == "STATIC_SYSTEM"
    assert gen.role_prompt == "STATIC_ROLE"
    assert gen.sd_caption_system_prompt == "STATIC_SD_SYSTEM"
    assert gen.sd_caption_role_prompt == "STATIC_SD_ROLE"


def test_sd_prompts_inherit_from_tenant_caption_prompts_when_sd_prompts_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Regression for Issue #50: when tenant provides custom caption prompts but leaves
    sd_caption_* prompts as null, SD prompts should inherit from tenant prompts
    (and must not be overwritten by static YAML).
    """
    monkeypatch.setattr(
        "publisher_v2.services.ai.get_static_config",
        lambda: _static_cfg(
            caption_system="STATIC_SYSTEM",
            caption_role="STATIC_ROLE",
            sd_system="STATIC_SD_SYSTEM",
            sd_role="STATIC_SD_ROLE",
        ),
    )

    cfg = OpenAIConfig(
        api_key="sk-test",
        system_prompt="TENANT_SYSTEM",
        role_prompt="TENANT_ROLE",
        sd_caption_system_prompt=None,
        sd_caption_role_prompt=None,
    )
    gen = CaptionGeneratorOpenAI(cfg)

    assert gen.sd_caption_system_prompt == "TENANT_SYSTEM"
    # Role prompt should be inherited (and keep SD role template for JSON/output contract).
    assert gen.sd_caption_role_prompt.startswith("TENANT_ROLE")
    assert "STATIC_SD_ROLE" in gen.sd_caption_role_prompt


