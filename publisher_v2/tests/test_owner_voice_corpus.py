"""PUB-050 AC1-AC3: `sample_voice_examples` — per-image sampling of the owner voice corpus.

The function under test is pure: given a corpus, a seed string and (optionally) a
platform-tag map plus the platforms being written, it returns the 4-6 examples that
this image's prompt should carry. The algorithm is pinned verbatim in the roadmap
item's Implementation Notes; these tests assert its observable contract, not its
internals.
"""

from __future__ import annotations

import json
import logging

import pytest

from publisher_v2.services.ai import sample_voice_examples

# Deliberately short: PUB-050 AC1 requires that the 500-token budget truncation
# (roughly 2000 characters) drops nothing from a 12-item profile, so the 4-6
# guarantee is about the sampler and not about the budget.
PROFILE: list[str] = [f"Example line number {i}." for i in range(1, 13)]


# ---------------------------------------------------------------------------
# AC1: four to six examples, all from the profile, no duplicates
# ---------------------------------------------------------------------------


def test_sample_voice_examples_returns_four_to_six_from_twelve_item_profile() -> None:
    result = sample_voice_examples(PROFILE, seed_source="image-001")

    assert 4 <= len(result) <= 6, f"a 12-item short profile must sample 4-6 examples, got {len(result)}"


def test_sample_voice_examples_result_has_no_duplicates_and_is_drawn_from_profile() -> None:
    result = sample_voice_examples(PROFILE, seed_source="image-001")

    assert len(set(result)) == len(result), f"the sample repeated an example: {result}"
    assert set(result) <= set(PROFILE), "the sample invented an example that is not in the profile"


# ---------------------------------------------------------------------------
# AC2: deterministic per seed, different across deliberately-chosen seeds
# ---------------------------------------------------------------------------


def test_sample_voice_examples_is_deterministic_for_same_seed() -> None:
    """The same image must get the same examples on every run — no wall-clock randomness."""
    first = sample_voice_examples(PROFILE, seed_source="image-001")
    second = sample_voice_examples(PROFILE, seed_source="image-001")

    assert first == second, "the same seed produced a different sample (order and membership must both match)"


def test_sample_voice_examples_differs_for_two_chosen_seeds() -> None:
    """Two seeds chosen against the pinned algorithm, not left to chance.

    Under the pinned sequence (sha256 -> `random.Random` -> `randint(4, 6)` as the
    FIRST draw), "alpha" yields a target of 4 and "seed-b" a target of 6 for this
    profile, so the two results differ in length regardless of how the shuffle
    falls. If this ever collides, the algorithm changed — do not just swap seeds.
    """
    a = sample_voice_examples(PROFILE, seed_source="alpha")
    b = sample_voice_examples(PROFILE, seed_source="seed-b")

    assert a != b, "two different seeds produced an identical sample; the seed is not reaching the sampler"


# ---------------------------------------------------------------------------
# AC3: platform tag preference (union semantics across enabled platforms)
# ---------------------------------------------------------------------------

EMAIL_TAGGED: list[str] = PROFILE[:6]
TELEGRAM_TAGGED: list[str] = PROFILE[6:9]
UNTAGGED: list[str] = PROFILE[9:]


def test_sample_voice_examples_prefers_email_tagged_examples_when_pool_is_large_enough() -> None:
    """Six email-tagged examples can fill the largest possible target (6) on their own."""
    result = sample_voice_examples(
        PROFILE,
        seed_source="image-001",
        platform_tags={"email": EMAIL_TAGGED},
        platforms=["email"],
    )

    assert 4 <= len(result) <= 6
    assert set(result) <= set(EMAIL_TAGGED), (
        f"an untagged example was sampled while the email-tagged pool could fill the target: {result}"
    )


def test_sample_voice_examples_ignores_a_tag_whose_text_is_not_in_the_profile() -> None:
    """An edit that touches one list and not the other must not crash caption generation."""
    tags = {"email": [*EMAIL_TAGGED, "A line that was deleted from the voice profile."]}

    result = sample_voice_examples(PROFILE, seed_source="image-001", platform_tags=tags, platforms=["email"])

    assert set(result) <= set(PROFILE), "a stale tag leaked text that is no longer in the profile into the sample"
    assert set(result) <= set(EMAIL_TAGGED), f"the stale tag disturbed the preference partition: {result}"
    assert 4 <= len(result) <= 6


def test_sample_voice_examples_unions_tags_across_multiple_enabled_platforms() -> None:
    """AC3 multi-platform note: one shared prompt covers every enabled platform.

    With two enabled platforms and disjoint tag sets of three each, the preferred
    pool is the six-item union. Since the target is at least four and neither
    platform alone has four, a correct union must contribute at least one example
    from each platform, and no untagged example may appear.
    """
    tags = {"telegram": TELEGRAM_TAGGED, "email": EMAIL_TAGGED[:3]}

    result = sample_voice_examples(
        PROFILE,
        seed_source="image-001",
        platform_tags=tags,
        platforms=["telegram", "email"],
    )

    union = set(TELEGRAM_TAGGED) | set(EMAIL_TAGGED[:3])
    assert 4 <= len(result) <= 6
    assert set(result) <= union, f"an untagged example was preferred over the tagged union: {result}"
    assert set(result) & set(TELEGRAM_TAGGED), "no telegram-tagged example survived the union"
    assert set(result) & set(EMAIL_TAGGED[:3]), "no email-tagged example survived the union"
    assert not set(result) & set(UNTAGGED)


# ---------------------------------------------------------------------------
# Review nit (post-green): a tag map that matches no enabled platform degrades
# to the untagged path in silence. An operator who tags "fetlife" (the publisher
# type) instead of "email" (the platform name) gets uniform sampling and no
# signal anywhere that their tags were ignored.
# ---------------------------------------------------------------------------

NO_MATCH_EVENT = "voice_profile_tags_matched_no_enabled_platform"


def _tag_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if NO_MATCH_EVENT in r.getMessage()]


def _tag_warning_payload(caplog: pytest.LogCaptureFixture) -> dict[str, object]:
    warnings = _tag_warnings(caplog)
    assert warnings, f"the unmatched-tag warning was not emitted: {caplog.text!r}"
    return json.loads(warnings[0])


# Security audit (post-green): `voice_profile_tags` keys have NO validator, so
# the key is arbitrary operator text. The warning fires exactly in the
# misconfiguration case, and the most plausible misconfiguration is an inverted
# mapping — {"<a whole example caption>": ["telegram"]} — which would print the
# owner's caption text into tenant logs once per image, forever.
# Both caps below are deliberately restated here rather than imported from
# `services.ai`. They are an independent statement of the contract: importing
# them would make the assertions agree with the source by construction, so
# loosening a cap would pass silently. Restated, it has to be changed twice, on
# purpose. Do not "tidy" these into imports.
MAX_LOGGED_TAG_KEY_CHARS = 32
INVERTED_KEY = "Her hands, patient in the low lamplight, and the knot she took her time over."
SENTINEL_TAG_VALUE = "SENTINEL-tagged-example-text-that-must-never-be-logged"

# Round-3 audit: `voice_profile` is capped at 20 entries by its validator,
# `voice_profile_tags` is capped at nothing. A map with hundreds of keys would
# put every one of them in this warning, once per image, indefinitely — log
# volume and cost, operator-controlled rather than attacker-controlled.
MAX_LOGGED_TAG_KEYS = 10


class TestUnmatchedTagKeyWarning:
    def test_sample_voice_examples_warns_when_no_tag_key_matches_an_enabled_platform(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="publisher_v2.services.ai")

        result = sample_voice_examples(
            PROFILE,
            seed_source="image-001",
            platform_tags={"fetlife": EMAIL_TAGGED},  # the publisher type, not the platform name
            platforms=["email"],
        )

        warnings = _tag_warnings(caplog)
        assert warnings, f"tags that match no enabled platform were dropped silently: {caplog.text!r}"
        # The log must be a side channel only: the function stays pure and still
        # returns the untagged sample for this seed.
        assert result == sample_voice_examples(PROFILE, seed_source="image-001")

    def test_sample_voice_examples_does_not_warn_when_no_tags_are_configured(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The default path for most tenants — an untagged corpus is not a misconfiguration."""
        caplog.set_level(logging.WARNING, logger="publisher_v2.services.ai")

        sample_voice_examples(PROFILE, seed_source="image-001")

        assert not _tag_warnings(caplog), "a tenant with no tags at all was warned about its tags"

    def test_sample_voice_examples_does_not_warn_when_a_tag_key_matches(self, caplog: pytest.LogCaptureFixture) -> None:
        """A correctly-tagged corpus must stay quiet, or the warning is noise nobody reads."""
        caplog.set_level(logging.WARNING, logger="publisher_v2.services.ai")

        sample_voice_examples(
            PROFILE,
            seed_source="image-001",
            platform_tags={"email": EMAIL_TAGGED, "fetlife": TELEGRAM_TAGGED},
            platforms=["email"],
        )

        assert not _tag_warnings(caplog), "a correctly-tagged corpus was reported as a misconfiguration"

    def test_warning_truncates_a_long_tag_key_so_caption_text_cannot_leak(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An inverted tag map must not print the owner's caption into the log.

        The contract is a plain prefix cut: every logged key is at most
        ``MAX_LOGGED_TAG_KEY_CHARS`` characters and is the key's leading slice,
        so a genuine platform name stays readable while a pasted caption cannot
        survive intact. (Both halves together mean ``key[:32]`` with no ellipsis
        appended — an ellipsis would push the entry to 33 characters.)
        """
        caplog.set_level(logging.WARNING, logger="publisher_v2.services.ai")
        assert len(INVERTED_KEY) > MAX_LOGGED_TAG_KEY_CHARS, "the fixture must exceed the cap to prove anything"

        sample_voice_examples(
            PROFILE,
            seed_source="image-001",
            platform_tags={INVERTED_KEY: ["telegram"]},  # key and value swapped by the operator
            platforms=["email"],
        )

        payload = _tag_warning_payload(caplog)
        logged_keys = payload["tag_keys"]
        assert isinstance(logged_keys, list)
        assert INVERTED_KEY not in caplog.text, "the full tag key text reached the log"
        assert all(len(str(k)) <= MAX_LOGGED_TAG_KEY_CHARS for k in logged_keys), logged_keys
        assert INVERTED_KEY[:MAX_LOGGED_TAG_KEY_CHARS] in caplog.text, (
            "the key was dropped entirely; a truncated prefix must remain so the warning is diagnosable"
        )

    def test_warning_logs_a_real_platform_name_intact(self, caplog: pytest.LogCaptureFixture) -> None:
        """Truncation must not cost the diagnostic: every real platform name is far under the cap."""
        caplog.set_level(logging.WARNING, logger="publisher_v2.services.ai")

        sample_voice_examples(
            PROFILE,
            seed_source="image-001",
            platform_tags={"instagram": EMAIL_TAGGED},
            platforms=["email"],
        )

        payload = _tag_warning_payload(caplog)
        assert payload["tag_keys"] == ["instagram"], payload
        assert payload["enabled_platforms"] == ["email"], payload

    def test_warning_never_logs_tag_values_or_extra_payload_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """The tagged text itself is sensitive operator free text and is never a log field."""
        caplog.set_level(logging.WARNING, logger="publisher_v2.services.ai")

        result = sample_voice_examples(
            PROFILE,
            seed_source="image-001",
            platform_tags={"fetlife": [SENTINEL_TAG_VALUE, *EMAIL_TAGGED]},
            platforms=["email"],
        )

        payload = _tag_warning_payload(caplog)
        assert SENTINEL_TAG_VALUE not in caplog.text, "a tagged example string was logged"
        for example in PROFILE:
            assert example not in caplog.text, f"profile text leaked into the log: {example!r}"
        # `tag_key_count` joined the payload with the key-count cap below; the
        # shape is fixed (always present), so a log query never has to branch.
        assert set(payload) == {"timestamp", "message", "tag_keys", "enabled_platforms", "tag_key_count"}, payload
        assert payload["tag_key_count"] == 1, "the count is part of the fixed shape, not a truncation-only extra"
        # Still a side channel: the sample itself is unchanged by the logging.
        assert result == sample_voice_examples(PROFILE, seed_source="image-001")

    @pytest.mark.parametrize("bad_key", [5, None], ids=["int-key", "none-key"])
    def test_a_non_string_tag_key_does_not_crash_the_warning(
        self, bad_key: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        """API-robustness guard, NOT a reachable production path.

        Pydantic enforces ``dict[str, list[str]]`` on both ``ContentConfig`` and
        ``OrchestratorContent``, so a non-string key cannot arrive from a real
        config — do not read this as a live defect. It matters because
        ``sample_voice_examples`` is a public module-level function this repo's
        own tests call directly, and because the crash is in the branch that
        exists *to diagnose* a malformed tag map: the happy path shrugs the same
        input off (``platform_tags.get(...)`` simply misses), while the warning
        raises. A diagnostic must not be more brittle than what it diagnoses.

        The key is only ever rendered for the log, so stringifying it there is
        enough; the sampler itself keeps treating it as an unmatched key.
        """
        caplog.set_level(logging.WARNING, logger="publisher_v2.services.ai")

        result = sample_voice_examples(
            PROFILE,
            seed_source="image-001",
            platform_tags={bad_key: [SENTINEL_TAG_VALUE]},  # type: ignore[dict-item]
            platforms=["email"],
        )

        payload = _tag_warning_payload(caplog)
        logged_keys = payload["tag_keys"]
        assert isinstance(logged_keys, list)
        assert all(isinstance(k, str) for k in logged_keys), logged_keys
        assert all(len(k) <= MAX_LOGGED_TAG_KEY_CHARS for k in logged_keys), logged_keys
        assert logged_keys == [str(bad_key)], logged_keys
        assert SENTINEL_TAG_VALUE not in caplog.text, "a tagged example string was logged"
        assert result == sample_voice_examples(PROFILE, seed_source="image-001")

    def test_warning_caps_how_many_tag_keys_it_logs_and_reports_the_real_total(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A huge tag map must not produce a huge log line, once per image, forever.

        ``voice_profile`` is capped at 20 entries by its validator; ``voice_profile_tags``
        is capped at nothing, so the misconfiguration this warning diagnoses is also the
        one that can make it enormous. The cap must not cost the diagnostic either: the
        line still reports how many keys there actually were.
        """
        caplog.set_level(logging.WARNING, logger="publisher_v2.services.ai")
        many = {f"platform-{i:03d}": [SENTINEL_TAG_VALUE] for i in range(50)}
        assert len(many) > MAX_LOGGED_TAG_KEYS, "the fixture must exceed the cap to prove anything"

        result = sample_voice_examples(
            PROFILE,
            seed_source="image-001",
            platform_tags=many,
            platforms=["email"],
        )

        payload = _tag_warning_payload(caplog)
        logged_keys = payload["tag_keys"]
        assert isinstance(logged_keys, list)
        assert len(logged_keys) <= MAX_LOGGED_TAG_KEYS, f"{len(logged_keys)} keys reached the log line"
        assert payload["tag_key_count"] == len(many), (
            "the warning under-reported the scale of the misconfiguration it exists to flag"
        )
        # The surviving keys keep every property the un-capped ones had.
        assert all(isinstance(k, str) for k in logged_keys), logged_keys
        assert all(len(k) <= MAX_LOGGED_TAG_KEY_CHARS for k in logged_keys), logged_keys
        assert logged_keys == sorted(logged_keys), f"the logged keys are no longer sorted: {logged_keys}"
        assert set(logged_keys) <= set(many), logged_keys
        assert SENTINEL_TAG_VALUE not in caplog.text, "a tagged example string was logged"
        assert result == sample_voice_examples(PROFILE, seed_source="image-001")
