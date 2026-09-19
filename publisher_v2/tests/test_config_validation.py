from __future__ import annotations

import pytest
from pydantic import ValidationError

from publisher_v2.config.schema import DropboxConfig, OpenAIConfig


def test_dropbox_folder_must_start_with_slash():
    with pytest.raises(ValidationError):
        DropboxConfig(
            app_key="key",
            app_secret="secret",
            refresh_token="refresh",
            image_folder="Photos",  # missing leading slash
        )


def test_openai_key_format_must_start_with_sk():
    with pytest.raises(ValidationError):
        OpenAIConfig(api_key="not-a-key")


# ---------- #81 (CAP-7): model validator checks shape, not prefix ----------


def test_newer_model_family_accepted():
    from publisher_v2.config.schema import OpenAIConfig

    cfg = OpenAIConfig(api_key="sk-test", caption_model="gpt-5-mini")
    assert cfg.caption_model == "gpt-5-mini"


def test_model_with_whitespace_rejected():
    import pytest as _pytest

    from publisher_v2.config.schema import OpenAIConfig

    with _pytest.raises(ValueError):
        OpenAIConfig(api_key="sk-test", caption_model="bad model")


def test_empty_model_rejected():
    import pytest as _pytest

    from publisher_v2.config.schema import OpenAIConfig

    with _pytest.raises(ValueError):
        OpenAIConfig(api_key="sk-test", caption_model="  ")
