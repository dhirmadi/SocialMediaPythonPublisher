"""Tests for build_analysis_context helper (PUB-041 Part C, AC-12..AC-16)."""

from __future__ import annotations

import inspect
import re

import pytest

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.ai import (
    CaptionGeneratorOpenAI,
    build_analysis_context,
)


def _base_analysis(**overrides) -> ImageAnalysis:
    defaults = dict(
        description="A serene fine-art figure study under soft window light.",
        mood="calm",
        tags=["portrait", "softlight"],
        nsfw=False,
        safety_labels=["adult_nudity_non_explicit"],
        subject="single subject",
        style="fine-art",
        lighting="soft directional",
        camera="50mm prime",
        clothing_or_accessories="rope harness",
        aesthetic_terms=["minimalist", "graphic"],
        pose="upright torso",
        composition="center-weighted",
        background="plain backdrop",
        color_palette="black and white",
    )
    defaults.update(overrides)
    return ImageAnalysis(**defaults)


def test_ac12_includes_optional_fields_when_present() -> None:
    """AC-12: lighting/composition/pose/aesthetic_terms/color_palette/style appear when non-None."""
    analysis = _base_analysis()
    out = build_analysis_context(analysis)
    assert "description=" in out
    assert "mood='calm'" in out
    assert "tags=" in out
    assert "lighting='soft directional'" in out
    assert "composition='center-weighted'" in out
    assert "pose='upright torso'" in out
    assert "aesthetic_terms=" in out
    assert "color_palette='black and white'" in out
    assert "style='fine-art'" in out


def test_ac13_none_fields_omitted() -> None:
    """AC-13: None fields are omitted entirely from output."""
    analysis = _base_analysis(
        lighting=None,
        composition=None,
        pose=None,
        aesthetic_terms=[],
        color_palette=None,
        style=None,
    )
    out = build_analysis_context(analysis)
    assert "lighting=" not in out
    assert "composition=" not in out
    assert "pose=" not in out
    assert "aesthetic_terms=" not in out
    assert "color_palette=" not in out
    assert "style=" not in out
    assert "None" not in out


def test_ac14_long_strings_truncated_at_50_chars() -> None:
    """AC-14: each string field truncated to <= 50 chars."""
    long = "x" * 200
    analysis = _base_analysis(lighting=long, composition=long, pose=long, color_palette=long, style=long)
    out = build_analysis_context(analysis)
    for field in ("lighting", "composition", "pose", "color_palette", "style"):
        match = re.search(rf"{field}='([^']*)'", out)
        assert match is not None, f"{field} missing from output"
        assert len(match.group(1)) <= 50


def test_ac14_aesthetic_terms_capped_at_10() -> None:
    """AC-14: aesthetic_terms list is truncated to first 10 items."""
    analysis = _base_analysis(aesthetic_terms=[f"t{i}" for i in range(25)])
    out = build_analysis_context(analysis)
    match = re.search(r"aesthetic_terms=(\[[^\]]*\])", out)
    assert match is not None
    rendered = match.group(1)
    assert "'t9'" in rendered
    assert "'t10'" not in rendered


def test_ac15_excluded_fields_never_included() -> None:
    """AC-15: nsfw, safety_labels, camera, clothing_or_accessories, background, subject excluded."""
    analysis = _base_analysis()
    out = build_analysis_context(analysis)
    for forbidden in ("nsfw", "safety_labels", "camera", "clothing_or_accessories", "background", "subject"):
        assert forbidden not in out, f"unexpected key '{forbidden}' in build_analysis_context output: {out}"


def test_ac16_call_sites_use_helper() -> None:
    """AC-16: generate, generate_with_sd, and _build_multi_prompt all use build_analysis_context."""
    sources = {
        "generate": inspect.getsource(CaptionGeneratorOpenAI.generate),
        "generate_with_sd": inspect.getsource(CaptionGeneratorOpenAI.generate_with_sd),
        "_build_multi_prompt": inspect.getsource(CaptionGeneratorOpenAI._build_multi_prompt),
    }
    for name, src in sources.items():
        assert "build_analysis_context" in src, f"{name} should use build_analysis_context helper"
        # The legacy inline construction must be gone.
        assert "description='{analysis.description}'" not in src, f"{name} still uses inline description string"


def test_empty_strings_treated_as_none() -> None:
    """Empty/whitespace strings should be treated as missing (no empty quotes in output)."""
    analysis = _base_analysis(lighting="   ", style="")
    out = build_analysis_context(analysis)
    assert "lighting=" not in out
    assert "style=" not in out


@pytest.mark.parametrize("field", ["lighting", "composition", "pose", "color_palette", "style"])
def test_string_at_exactly_50_chars_not_truncated(field: str) -> None:
    """Boundary: a field exactly 50 chars long should not get further truncated."""
    val = "y" * 50
    analysis = _base_analysis(**{field: val})
    out = build_analysis_context(analysis)
    match = re.search(rf"{field}='([^']*)'", out)
    assert match is not None
    assert match.group(1) == val
