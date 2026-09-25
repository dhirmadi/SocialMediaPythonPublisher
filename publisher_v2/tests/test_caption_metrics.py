"""PUB-049 AC1/AC2: the caption diversity metrics in ``utils/caption_metrics.py``.

Every AC2 value in this file was computed **by hand** and the arithmetic is
shown in the test that uses it. That is the whole point of AC2: the expected
numbers must not come from running the implementation, or the test only asserts
that the code agrees with itself.

Conventions this file pins for the implementer (deviating from any of them
means a test here fails, and the test is right unless the spec changes):

- Tokenization is the shared word tokenizer promoted out of
  ``utils/captions.py`` (``_words``). There must not be a second tokenizer.
- ``sentence_word_count_variance`` uses **population** variance (divide by N).
- ``tfidf_bigram_cosine`` uses the convention documented in
  ``test_tfidf_bigram_cosine_to_history_matches_hand_computed_value``.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.utils.caption_metrics import (
    distinct_n,
    opener_closer_trigram_share,
    sentence_word_count_variance,
    tells_lexicon_hit_rate,
    tfidf_bigram_cosine,
    two_sentence_emoji_rhythm_share,
    vision_field_overlap,
)
from publisher_v2.utils.captions import trigram_jaccard

FIXTURES = Path(__file__).parent / "fixtures" / "captions"

# The 0.04 ceiling the spec's Problem section measured: six captions any editor
# would call clones score at most this on the only diversity metric in the code.
TRIGRAM_CEILING = 0.04


def _clone_set() -> list[str]:
    return json.loads((FIXTURES / "clone_set.json").read_text())["captions"]


def _thresholds() -> dict[str, dict[str, object]]:
    """The committed bars the harness scores against (AC4 schema)."""
    return json.loads((FIXTURES / "caption_eval_thresholds.json").read_text())


# --- AC1: the gap between what trigram_jaccard sees and what the owner sees ---


def test_clone_set_flagged_by_new_metrics_not_by_trigram() -> None:
    """The constructed clone set must be caught by the new metrics and missed by the old one.

    ``clone_set.json`` is six captions built to the rule documented in
    ``fixtures/captions/README.md``: identical three-word opener, identical
    closing sentence, under 15% word-count spread, deliberately disjoint
    middles. Both halves of this assertion matter — a harness that flagged the
    clone set but where ``trigram_jaccard`` also flagged it would not justify
    this item existing.
    """
    captions = _clone_set()
    assert len(captions) == 6
    thresholds = _thresholds()

    # Side one: the existing metric stays blind. Measured across all fifteen
    # pairs, the maximum is 0.0323 (see README.md) — under the 0.04 ceiling.
    worst_trigram = max(trigram_jaccard(a, b) for a, b in itertools.combinations(captions, 2))
    assert worst_trigram <= TRIGRAM_CEILING, f"clone set no longer sits under the measured ceiling: {worst_trigram}"

    # Side two: the new metrics cross their committed bar. Both are
    # ``direction: "max"`` metrics — a score above ``value`` is the regression.
    tells_bar = thresholds["tells_lexicon_hit_rate"]
    assert tells_bar["direction"] == "max"
    tells_rate = tells_lexicon_hit_rate(captions)
    assert tells_rate > float(tells_bar["value"]), f"default lexicon missed the clone set (rate {tells_rate})"

    cosine_bar = thresholds["tfidf_bigram_cosine"]
    assert cosine_bar["direction"] == "max"
    worst_cosine = max(
        tfidf_bigram_cosine(caption, [other for other in captions if other != caption]) for caption in captions
    )
    assert worst_cosine > float(cosine_bar["value"]), f"TF-IDF cosine missed the clone set ({worst_cosine})"


# --- AC2: one test per metric, one hand-computed value each ---


def test_opener_closer_trigram_share_matches_hand_computed_value() -> None:
    """Share of captions whose opening or closing 3-gram is shared with another caption.

    Opener 3-gram = first three word tokens; closer 3-gram = last three.

      c1 "Morning light on the wall."      opener (morning,light,on)   closer (on,the,wall)
      c2 "Morning light on the floor."     opener (morning,light,on)   closer (on,the,floor)
      c3 "Rope coils in the dark."         opener (rope,coils,in)      closer (in,the,dark)
      c4 "Smoke drifts in the dark."       opener (smoke,drifts,in)    closer (in,the,dark)
      c5 "Quiet settles over everything slowly."
                                           opener (quiet,settles,over) closer (over,everything,slowly)

    c1 and c2 share an opener. c3 and c4 share a closer. c5 shares neither.
    Hand computation: 4 flagged / 5 captions = 0.8.
    """
    captions = [
        "Morning light on the wall.",
        "Morning light on the floor.",
        "Rope coils in the dark.",
        "Smoke drifts in the dark.",
        "Quiet settles over everything slowly.",
    ]

    assert opener_closer_trigram_share(captions) == pytest.approx(0.8)


def test_sentence_and_word_count_variance_matches_hand_computed_value() -> None:
    """Population variance (divide by N, not N-1) of sentence counts and word counts.

    Sentences split on terminal punctuation (. ! ?).

      c1 "Rope tightens."                               1 sentence,  2 words
      c2 "Warm light fills everything."                 1 sentence,  4 words
      c3 "Quiet now. She waits there. Breathe."         3 sentences, 6 words
      c4 "Dust settles. The floor is cold. Nothing moves."
                                                        3 sentences, 8 words

    Sentence counts [1, 1, 3, 3]: mean = 8/4 = 2.
      deviations -1, -1, 1, 1 -> squares 1+1+1+1 = 4 -> 4/4 = 1.0
    Word counts [2, 4, 6, 8]: mean = 20/4 = 5.
      deviations -3, -1, 1, 3 -> squares 9+1+1+9 = 20 -> 20/4 = 5.0

    (Sample variance would give 4/3 and 20/3; the spec pins population.)
    """
    captions = [
        "Rope tightens.",
        "Warm light fills everything.",
        "Quiet now. She waits there. Breathe.",
        "Dust settles. The floor is cold. Nothing moves.",
    ]

    result = sentence_word_count_variance(captions)

    assert result["sentence_count_variance"] == pytest.approx(1.0)
    assert result["word_count_variance"] == pytest.approx(5.0)


def test_two_sentence_emoji_rhythm_share_matches_hand_computed_value() -> None:
    """Fraction of captions in the "exactly two sentences, then a trailing emoji" rhythm.

    A trailing emoji (and the whitespace before it) is stripped before the
    sentences are counted, so the emoji is never itself a third sentence.

      c1 "Rope tightens. She breathes out. 🔥"   2 sentences + trailing emoji -> match
      c2 "Warm light. It lingers."               2 sentences, no emoji        -> no
      c3 "One sentence only 🔥"                  1 sentence + emoji           -> no
      c4 "Dust settles. Nothing moves. Then quiet. ✨"
                                                 3 sentences + emoji          -> no

    Hand computation: 1 match / 4 captions = 0.25.
    """
    captions = [
        "Rope tightens. She breathes out. 🔥",
        "Warm light. It lingers.",
        "One sentence only 🔥",
        "Dust settles. Nothing moves. Then quiet. ✨",
    ]

    assert two_sentence_emoji_rhythm_share(captions) == pytest.approx(0.25)


def test_tells_lexicon_hit_rate_matches_hand_computed_value() -> None:
    """Fraction of captions matching at least one lexicon pattern, case-insensitively.

    The lexicon is passed explicitly so the value is hand-computable without
    depending on the default list's current contents.

      lexicon = [r"isn't just", r"in a world where", r"a testament to"]

      c1 "This isn't just rope, it's trust."               -> hit ("isn't just")
      c2 "In a world where everything rushes, she waits."  -> hit (capitalised; matching
                                                              must be case-insensitive)
      c3 "A testament to patience."                        -> hit (also capitalised)
      c4 "Rope, skin, and the slow evening."               -> no
      c5 "She waits by the window."                        -> no

    Hand computation: 3 hits / 5 captions = 0.6.
    """
    lexicon = [r"isn't just", r"in a world where", r"a testament to"]
    captions = [
        "This isn't just rope, it's trust.",
        "In a world where everything rushes, she waits.",
        "A testament to patience.",
        "Rope, skin, and the slow evening.",
        "She waits by the window.",
    ]

    assert tells_lexicon_hit_rate(captions, lexicon) == pytest.approx(0.6)


def test_distinct_1_and_distinct_2_match_hand_computed_value() -> None:
    """Distinct-n = unique n-grams / total n-grams across the whole caption set.

    N-grams never cross a caption boundary.

      c1 "the rope is the rope"  words: the rope is the rope       (5 tokens)
      c2 "the rope is warm"      words: the rope is warm           (4 tokens)
      c3 "quiet"                 words: quiet                      (1 token)

    distinct-1: total unigrams 5 + 4 + 1 = 10.
      unique {the, rope, is, warm, quiet} = 5  ->  5/10 = 0.5

    distinct-2: bigrams per caption:
      c1 (the,rope) (rope,is) (is,the) (the,rope)                  -> 4
      c2 (the,rope) (rope,is) (is,warm)                            -> 3
      c3 none (a one-word caption yields no bigram)                -> 0
      total 7; unique {(the,rope), (rope,is), (is,the), (is,warm)} = 4
      ->  4/7 = 0.571428...
    """
    captions = ["the rope is the rope", "the rope is warm", "quiet"]

    assert distinct_n(captions, 1) == pytest.approx(0.5)
    assert distinct_n(captions, 2) == pytest.approx(4 / 7)


def test_tfidf_bigram_cosine_to_history_matches_hand_computed_value() -> None:
    """Cosine of a caption's bigram TF-IDF vector against the history corpus.

    The convention pinned here (the implementation must match it exactly):

      * Terms are word **bigrams**, built per document — bigrams never cross a
        document boundary, so the history is not simply concatenated into one
        string.
      * tf = raw bigram count in the document.
      * idf(t) = ln((1 + N) / (1 + df(t))) + 1, where N = len(history) and
        df(t) = number of history documents containing t. Smoothed
        (scikit-learn's ``smooth_idf=True`` form) so that a term present in
        every history document still carries weight 1.0 rather than 0.
      * The history is represented as one aggregated pseudo-document whose
        bigram counts are the sum of the per-document counts.
      * Both vectors are L2-normalised; the score is their dot product.
      * An empty caption or empty history scores 0.0.

    Hand computation:

      history = ["red rope glows", "red rope falls"], N = 2
        doc1 bigrams: (red,rope), (rope,glows)
        doc2 bigrams: (red,rope), (rope,falls)
        df: (red,rope)=2, (rope,glows)=1, (rope,falls)=1
        idf(red,rope)   = ln(3/3) + 1 = 1.0
        idf(rope,glows) = ln(3/2) + 1 = 1.4054651081081644  (call it a)
        idf(rope,falls) = ln(3/2) + 1 = a
        a^2 = 1.9753321701094941

      caption = "red rope glows"
        tf: (red,rope)=1, (rope,glows)=1
        vector: [1*1.0, 1*a]                  ||v|| = sqrt(1 + a^2)
      aggregated history
        tf: (red,rope)=2, (rope,glows)=1, (rope,falls)=1
        vector: [2*1.0, 1*a, 1*a]             ||h|| = sqrt(4 + a^2 + a^2)

      dot over the shared dimensions = (1*1.0)(2*1.0) + (a)(a) = 2 + a^2
      cosine = (2 + a^2) / (sqrt(1 + a^2) * sqrt(4 + 2*a^2))
             = 3.9753321701094941 / (1.7249150038...  * 2.8195...)
             = 0.8173423172931453
    """
    a = 1.0 + math.log(1.5)
    expected = (2 + a**2) / (math.sqrt(1 + a**2) * math.sqrt(4 + 2 * a**2))
    assert expected == pytest.approx(0.8173423172931453)  # the arithmetic above, checked

    score = tfidf_bigram_cosine("red rope glows", ["red rope glows", "red rope falls"])

    assert score == pytest.approx(0.8173423172931453)


def test_vision_field_content_word_overlap_matches_hand_computed_value() -> None:
    """Share of the caption's unique content words that also appear in the analysis fields.

    Content words are the caption's word tokens minus stopwords; the module's
    stopword set must contain at least {the, is, and, on, a}, which is what this
    input relies on.

      caption "The rope is tight and the lantern glows on the floor."
        tokens: the rope is tight and the lantern glows on the floor
        minus stopwords (the, is, and, on): rope, tight, lantern, glows, floor
        unique content words = 5

      analysis text fields:
        description        "A woman bound with rope on a wooden floor"  -> rope, floor
        tags               ["lantern", "shadow"]                        -> lantern
        mood               "calm"
        distinctive_detail "a frayed rope end"                          -> rope

      present:     rope, lantern, floor   (3)
      not present: tight, glows           (2)

    Hand computation: 3 / 5 = 0.6.
    """
    analysis = ImageAnalysis(
        description="A woman bound with rope on a wooden floor",
        mood="calm",
        tags=["lantern", "shadow"],
        distinctive_detail="a frayed rope end",
    )

    score = vision_field_overlap("The rope is tight and the lantern glows on the floor.", analysis)

    assert score == pytest.approx(0.6)
