from __future__ import annotations

import pytest
from pydantic import ValidationError

from publisher_v2.config.schema import OpenAIConfig


def test_separate_models_configuration():
    """Test that separate vision and caption models can be configured"""
    config = OpenAIConfig(
        api_key="sk-test123",
        vision_model="gpt-4o",
        caption_model="gpt-4o-mini",
    )
    assert config.vision_model == "gpt-4o"
    assert config.caption_model == "gpt-4o-mini"


def test_legacy_model_field_backward_compatibility():
    """Test that legacy 'model' field can be set (loader handles compatibility)"""
    config = OpenAIConfig(
        api_key="sk-test123",
        model="gpt-4o-mini",
        vision_model="gpt-4o-mini",
        caption_model="gpt-4o-mini",
    )
    # When all fields are explicitly set
    assert config.vision_model == "gpt-4o-mini"
    assert config.caption_model == "gpt-4o-mini"
    assert config.model == "gpt-4o-mini"


def test_defaults_when_no_model_specified():
    """Test default models when nothing is specified"""
    config = OpenAIConfig(
        api_key="sk-test123",
    )
    assert config.vision_model == "gpt-4o"
    assert config.caption_model == "gpt-4o-mini"


def test_invalid_model_name_rejected():
    """Test that invalid model names are rejected"""
    with pytest.raises(ValidationError):
        OpenAIConfig(
            api_key="sk-test123",
            vision_model="invalid-model-123",
        )


def test_explicit_separate_models_override():
    """Test that explicitly setting separate models works"""
    config = OpenAIConfig(
        api_key="sk-test123",
        vision_model="gpt-4o",
        caption_model="gpt-4o-mini",
    )
    assert config.vision_model == "gpt-4o"
    assert config.caption_model == "gpt-4o-mini"


def test_all_supported_model_prefixes():
    """Test that all supported model prefixes are accepted"""
    valid_models = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        "o1-preview",
        "o3-mini",
    ]
    for model in valid_models:
        config = OpenAIConfig(
            api_key="sk-test123",
            vision_model=model,
            caption_model=model,
        )
        assert config.vision_model == model
        assert config.caption_model == model

