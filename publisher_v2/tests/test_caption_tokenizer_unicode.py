"""#144 item 6: the trigram tokenizer dropped non-ASCII letters.

`[a-z0-9']+` split "café" into "caf" + "" and "naïve" into "na" + "ve", so the
similarity gate compared mangled tokens for any caption with accented words —
under-counting similarity exactly where the wording repeats.
"""

from __future__ import annotations

from publisher_v2.utils.captions import trigram_jaccard


def test_accented_words_stay_whole() -> None:
    from publisher_v2.utils.captions import _words

    assert _words("café naïve") == ["café", "naïve"]


def test_identical_accented_captions_score_one() -> None:
    caption = "A café evening, naïve and slow, rope and skin"

    assert trigram_jaccard(caption, caption) == 1.0


def test_accent_difference_is_not_a_token_split() -> None:
    """"café" and "cafe" are different words — not "caf" plus an empty token."""
    assert trigram_jaccard("the café is warm tonight", "the cafe is warm tonight") < 1.0
    assert trigram_jaccard("the café is warm tonight", "the café is warm tonight") == 1.0


def test_underscores_still_separate_words() -> None:
    from publisher_v2.utils.captions import _words

    assert _words("rope_and_skin") == ["rope", "and", "skin"]


def test_ascii_behaviour_is_unchanged() -> None:
    from publisher_v2.utils.captions import _words

    assert _words("Don't stop; rope, skin 42") == ["don't", "stop", "rope", "skin", "42"]
