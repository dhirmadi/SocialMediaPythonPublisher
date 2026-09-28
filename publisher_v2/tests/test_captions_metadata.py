"""PUB-084 AC17 (#281): ``build_metadata_phase2`` output is pinned before its field-map refactor.

A refactor guard: the expected dicts below were captured from the implementation as it
stood before the refactor (2026-09-28). Key order is asserted as well as content, because
the sidecar writer emits keys in insertion order and the sidecar must stay byte-identical.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.utils.captions import build_metadata_phase2

_FIXTURES: dict[str, ImageAnalysis] = {
    "all_fields": ImageAnalysis(
        description="A woman kneels on a wooden floor",
        mood="calm",
        tags=["rope", " ", "", "shibari", "rope"],
        nsfw=True,
        safety_labels=["nudity", "", "  ", "nudity"],
        sd_caption="sd prompt, kneeling, rope",
        subject="a kneeling woman",
        style="fine-art monochrome",
        lighting="soft window light",
        camera="85mm, shallow depth",
        clothing_or_accessories="hemp rope",
        aesthetic_terms=["chiaroscuro", " ", "minimal"],
        pose="kneeling, head bowed",
        composition="centered, negative space left",
        background="bare plaster wall",
        color_palette="warm greys",
        alt_text="A woman in rope kneeling by a wall.",
        distinctive_detail="a single loose strand over her shoulder",
        sensory_detail=["rough hemp", "cool floor"],
        mood_note="quiet surrender",
    ),
    "description_only": ImageAnalysis(description="d", mood="m"),
    "empty_strings_and_blank_lists": ImageAnalysis(
        description="d",
        mood="m",
        tags=[" ", ""],
        safety_labels=[],
        subject="",
        style="",
        lighting="",
        camera="",
        clothing_or_accessories="",
        aesthetic_terms=["  "],
        pose="",
        composition="",
        background="",
        color_palette="",
        alt_text="",
        distinctive_detail="",
    ),
    "whitespace_strings_kept": ImageAnalysis(description="d", mood="m", subject="  ", alt_text=" alt ", tags=["a"]),
}

# Captured verbatim, quirks included: blank list items are dropped but duplicates are not,
# a list of only blanks still yields an empty list, and whitespace-only strings are kept.
_EXPECTED: dict[str, dict[str, Any]] = {
    "all_fields": {
        "subject": "a kneeling woman",
        "lighting": "soft window light",
        "pose": "kneeling, head bowed",
        "camera": "85mm, shallow depth",
        "materials": "hemp rope",
        "art_style": "fine-art monochrome",
        "composition": "centered, negative space left",
        "background": "bare plaster wall",
        "color_palette": "warm greys",
        "alt_text": "A woman in rope kneeling by a wall.",
        "distinctive_detail": "a single loose strand over her shoulder",
        "tags": ["rope", "shibari", "rope"],
        "aesthetic_terms": ["chiaroscuro", "minimal"],
        "moderation": ["nudity", "nudity"],
    },
    "description_only": {},
    "empty_strings_and_blank_lists": {"tags": [], "aesthetic_terms": []},
    "whitespace_strings_kept": {"subject": "  ", "alt_text": " alt ", "tags": ["a"]},
}


@pytest.mark.parametrize("fixture", list(_FIXTURES))
def test_build_metadata_phase2_output_unchanged(fixture: str) -> None:
    meta = build_metadata_phase2(_FIXTURES[fixture])

    expected = _EXPECTED[fixture]
    assert meta == expected
    assert list(meta) == list(expected), "key order drives the sidecar bytes"
    assert json.dumps(meta) == json.dumps(expected)
