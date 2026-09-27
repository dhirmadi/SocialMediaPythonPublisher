"""Tests of the shared test fakes and builders in ``caption_pipeline_fakes`` (PUB-084 AC4, AC7).

The fakes stand in for external systems across the suite, so their own contract is pinned here:
a scripted ``FakeOpenAI`` replays its script in order, and ``make_app_config`` layers overrides
on top of valid defaults without switching validation off.
"""

from __future__ import annotations

import inspect
import json

import caption_pipeline_fakes as fakes
import pytest
from pydantic import ValidationError

from publisher_v2.config.schema import (
    ApplicationConfig,
    FeaturesConfig,
    ManagedStorageConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.services import ai as ai_module


def _content(resp: object) -> str:
    return resp.choices[0].message.content  # type: ignore[attr-defined]


async def test_fake_openai_replays_script_in_order(fake_openai) -> None:
    """AC4: payloads and an exception are replayed in call order; the last entry repeats once exhausted."""
    assert "script" in inspect.signature(fakes.FakeOpenAI).parameters, "FakeOpenAI has no scripted-response mode"

    boom = RuntimeError("scripted outage")
    fake = fake_openai(script=["first reply", {"caption": "second"}, boom, "fourth reply"])

    # The fixture installs the fake where the production code builds its client.
    client = ai_module.AsyncOpenAI(api_key="sk-test", max_retries=0)
    assert client is fake
    assert fake.client_kwargs == [{"api_key": "sk-test", "max_retries": 0}]  # pragma: allowlist secret

    first = await client.chat.completions.create(model="m", messages=[{"role": "user", "content": "one"}])
    assert _content(first) == "first reply"

    second = await client.chat.completions.create(model="m", messages=[{"role": "user", "content": "two"}])
    assert json.loads(_content(second)) == {"caption": "second"}

    with pytest.raises(RuntimeError) as excinfo:
        await client.chat.completions.create(model="m", messages=[{"role": "user", "content": "three"}])
    assert excinfo.value is boom

    fourth = await client.chat.completions.create(model="m", messages=[{"role": "user", "content": "four"}])
    assert _content(fourth) == "fourth reply"

    # Exhausted: the last scripted entry is replayed.
    fifth = await client.chat.completions.create(model="m", messages=[{"role": "user", "content": "five"}])
    assert _content(fifth) == "fourth reply"

    # Every call is recorded in order, including the one that raised.
    assert [c["messages"][0]["content"] for c in fake.calls] == ["one", "two", "three", "four", "five"]


def test_make_app_config_applies_overrides() -> None:
    """AC7: overrides land on top of valid defaults; untouched sections keep the defaults; validation stays on."""
    assert hasattr(fakes, "make_app_config"), "caption_pipeline_fakes has no make_app_config(**overrides) helper"
    make_app_config = fakes.make_app_config

    default = make_app_config()
    assert isinstance(default, ApplicationConfig)
    assert default.dropbox is not None and default.managed is None
    assert default.storage_paths.image_folder == "/Photos"
    assert default.openai.api_key
    assert default.content.archive is False and default.content.debug is False

    cfg = make_app_config(
        features=FeaturesConfig(delete_enabled=False),
        openai=OpenAIConfig(api_key="sk-other", caption_model="gpt-4o"),
        content={"archive": True},
        platforms=PlatformsConfig(),
    )
    # Model-instance overrides replace the section.
    assert cfg.features.delete_enabled is False
    assert cfg.openai.caption_model == "gpt-4o"
    # Dict overrides merge onto that section's defaults.
    assert cfg.content.archive is True
    assert cfg.content.debug is False
    assert cfg.content.hashtag_string == default.content.hashtag_string
    # Sections not overridden keep the defaults.
    assert cfg.dropbox == default.dropbox
    assert cfg.storage_paths == default.storage_paths

    # Choosing managed storage replaces the default Dropbox provider (exactly one provider is valid).
    managed = make_app_config(
        managed=ManagedStorageConfig(
            access_key_id="a", secret_access_key="b", endpoint_url="https://r2.example.com", bucket="bkt"
        )
    )
    assert managed.managed is not None and managed.dropbox is None

    with pytest.raises(ValidationError):
        make_app_config(content={"archive": "definitely-not-a-bool"})
