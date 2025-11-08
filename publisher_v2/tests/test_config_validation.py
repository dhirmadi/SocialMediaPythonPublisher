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



