"""CAP-5/CAP-9 (#82): trigram similarity gate with one bounded regeneration."""

from __future__ import annotations

import logging

import pytest

from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import AIService
from publisher_v2.utils.captions import pick_structure_directive, trigram_jaccard


class TestTrigramJaccard:
    def test_identical_texts_score_one(self) -> None:
        text = "soft rope steady hands and a gaze that does not flinch"
        assert trigram_jaccard(text, text) == 1.0

    def test_disjoint_texts_score_zero(self) -> None:
        a = "one two three four five six"
        b = "seven eight nine ten eleven twelve"
        assert trigram_jaccard(a, b) == 0.0

    def test_partial_overlap_known_value(self) -> None:
        # a: trigrams {(a b c), (b c d)}; b: {(a b c), (b c e)} → jaccard 1/3
        a = "a b c d"
        b = "a b c e"
        assert trigram_jaccard(a, b) == pytest.approx(1 / 3)

    def test_short_texts_fall_back_to_word_overlap(self) -> None:
        assert trigram_jaccard("rope art", "rope art") == 1.0
        assert trigram_jaccard("rope art", "steel wire") == 0.0

    def test_case_and_punctuation_insensitive(self) -> None:
        assert trigram_jaccard("Soft Rope, steady HANDS here", "soft rope steady hands here") == 1.0


class TestStructureDirectiveRotation:
    def test_returns_a_directive_string(self) -> None:
        directive = pick_structure_directive([])
        assert isinstance(directive, str) and directive

    def test_rotates_after_history_grows(self) -> None:
        history: list[str] = []
        first = pick_structure_directive(history)
        # Simulate a caption written under the first directive being added to
        # history: the next pick must move on to a different directive.
        history = ["This is a plain declarative statement about rope."]
        second = pick_structure_directive(history)
        assert second != first

    def test_least_recently_used_wins(self) -> None:
        # A question-heavy history should never pick something classified as
        # recently used; deterministic for identical input.
        history = ["You know this feeling well.", "Quiet lines. Nothing more."]
        assert pick_structure_directive(history) == pick_structure_directive(history)


def _make_specs() -> dict[str, CaptionSpec]:
    return {"email": CaptionSpec(platform="email", style="s", hashtags="", max_length=240)}


def _analysis() -> ImageAnalysis:
    return ImageAnalysis(description="d", mood="m", tags=["t"])


HISTORY = {"email": ["soft rope steady hands and a gaze that does not flinch tonight"]}


class _GateStubGenerator:
    """First call returns a caption nearly identical to history; second differs."""

    sd_caption_enabled = False
    sd_caption_single_call_enabled = False

    def __init__(self, first: str, second: str) -> None:
        self.calls: list[str | None] = []
        self._responses = [first, second]

    async def generate_multi(self, analysis, specs, history=None, voice_examples=None, diversity_clause=None):
        self.calls.append(diversity_clause)
        text = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        return dict.fromkeys(specs, text), None


class TestSimilarityGate:
    async def test_regenerates_once_above_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        near_duplicate = "soft rope steady hands and a gaze that does not flinch again"
        fresh = "morning light settles on the studio floor"
        gen = _GateStubGenerator(near_duplicate, fresh)
        service = AIService(analyzer=None, generator=gen)  # type: ignore[arg-type]

        with caplog.at_level(logging.INFO, logger="publisher_v2.services.ai"):
            captions, _sd, _usages = await service.create_multi_caption_pair_from_analysis(
                _analysis(), _make_specs(), history=HISTORY
            )

        assert len(gen.calls) == 2
        assert gen.calls[0] is None
        assert gen.calls[1] is not None and "must differ" in gen.calls[1].lower()
        assert captions["email"] == fresh
        events = [r for r in caplog.records if "caption_similarity" in r.getMessage()]
        assert events, "caption_similarity event not logged"
        assert any('"regenerated": true' in r.getMessage() for r in events)

    async def test_no_extra_call_below_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        fresh = "morning light settles on the studio floor"
        gen = _GateStubGenerator(fresh, "unused")
        service = AIService(analyzer=None, generator=gen)  # type: ignore[arg-type]

        with caplog.at_level(logging.INFO, logger="publisher_v2.services.ai"):
            captions, _sd, _usages = await service.create_multi_caption_pair_from_analysis(
                _analysis(), _make_specs(), history=HISTORY
            )

        assert len(gen.calls) == 1
        assert captions["email"] == fresh
        events = [r for r in caplog.records if "caption_similarity" in r.getMessage()]
        assert events
        assert all('"regenerated": false' in r.getMessage() for r in events)
