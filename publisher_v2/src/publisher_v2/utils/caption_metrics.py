"""Caption diversity metrics for the evaluation harness (PUB-049).

Pure functions, no I/O and no new runtime dependency: the TF-IDF is hand-rolled
over word bigrams rather than pulled in from scikit-learn.

Tokenization is *not* defined here. Every function below tokenizes through
``publisher_v2.utils.captions.words`` and builds n-grams through
``publisher_v2.utils.captions.word_ngrams`` — the same helpers
``trigram_jaccard`` uses — so there is exactly one definition in the codebase of
how a caption becomes words and n-grams.

Conventions pinned by the spec (do not change these without changing the spec:
PUB-051/PUB-052 compare these numbers across items):

* ``sentence_word_count_variance`` uses **population** variance (divide by N).
* ``tfidf_bigram_cosine`` uses smoothed idf ``ln((1 + N) / (1 + df)) + 1`` and
  compares the caption against the history as one aggregated pseudo-document.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import fields as dataclass_fields

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.utils.captions import word_ngrams, words

# --- shared text helpers -----------------------------------------------------

# Sentence boundary: any run of terminal punctuation.
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")

# A trailing emoji (pictographs, dingbats, symbols and variation selectors).
# Matched only at the very end of a caption, so it is stripped before sentences
# are counted and never becomes a sentence of its own.
_TRAILING_EMOJI_RE = re.compile(r"(?:[←-⇿⌀-➿⬀-⯿︀-️\U0001f000-\U0001faff]|\s)+$")
_EMOJI_CHAR_RE = re.compile(r"[←-⇿⌀-➿⬀-⯿\U0001f000-\U0001faff]")

# Function words excluded from "content words" in ``vision_field_overlap``.
STOPWORDS: frozenset[str] = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "hers",
        "him",
        "his",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "nor",
        "not",
        "of",
        "on",
        "once",
        "or",
        "our",
        "ours",
        "out",
        "over",
        "she",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "too",
        "up",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "will",
        "with",
        "you",
        "your",
        "yours",
    ]
)

# The analysis fields whose text a caption can legitimately echo. Only public
# ``ImageAnalysis`` fields; ``nsfw``/``safety_labels``/``sd_caption`` are
# excluded because they are machine plumbing, not descriptive prose.
_VISION_TEXT_FIELDS: tuple[str, ...] = (
    "description",
    "mood",
    "tags",
    "subject",
    "style",
    "lighting",
    "camera",
    "clothing_or_accessories",
    "aesthetic_terms",
    "pose",
    "composition",
    "background",
    "color_palette",
    "alt_text",
    "distinctive_detail",
    "sensory_detail",
    "mood_note",
)

# --- the tells lexicon -------------------------------------------------------

# One regex per line, each with the reason it is a tell. Matched
# case-insensitively with ``re.search``. This list is meant to be curated: add a
# pattern and a comment, nothing else changes. Callers may pass their own list.
DEFAULT_TELLS_LEXICON: list[str] = [
    r"there\s*(?:is|'s)\s+something\s+about",  # the stock "There is something about X" opener
    r"(?:is|are|was|were)n[']?t\s+just",  # "this isn't just rope, it's trust" — the false-contrast move
    r"not\s+just\s+a\b",  # same contrast, positive form
    r"more\s+than\s+just\b",  # same contrast again
    r"in\s+a\s+world\s+where",  # trailer-voice scene setting
    r"a\s+testament\s+to",  # stock praise noun phrase
    r"let[']?s\s+be\s+honest",  # fake candour
    r"whether\s+you[']?re\b",  # the "whether you're X or Y" audience hedge
    r"at\s+the\s+end\s+of\s+the\s+day",  # filler conclusion
    r"when\s+it\s+comes\s+to\b",  # filler transition
    r"dive\s+(?:in|into)\b",  # marketing verb
    r"elevate\s+your\b",  # marketing verb
    r"unlock\s+the\b",  # marketing verb
    r"speaks\s+volumes",  # stock closer
    r"let\s+that\s+sink\s+in",  # stock closer
    r"perfect\s+blend\s+of",  # stock noun phrase
    r"in\s+today[']?s\s+\w+",  # "in today's fast-paced world"
    r"game[\s-]?changer",  # stock superlative
]


def _sentence_count(text: str) -> int:
    """Number of sentences in ``text`` (split on terminal punctuation)."""
    return len([part for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()])


def _strip_trailing_emoji(text: str) -> tuple[str, bool]:
    """Return ``(text without its trailing emoji run, whether there was one)``."""
    stripped = text.rstrip()
    match = _TRAILING_EMOJI_RE.search(stripped)
    if not match or not _EMOJI_CHAR_RE.search(match.group(0)):
        return stripped, False
    return stripped[: match.start()].rstrip(), True


def _population_variance(values: list[float]) -> float:
    """Population variance (divide by N), 0.0 for an empty input."""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


# --- the seven metrics -------------------------------------------------------


def opener_closer_trigram_share(captions: list[str]) -> float:
    """Share of captions sharing an opening or closing 3-gram with another caption.

    The opener 3-gram is the first three word tokens, the closer 3-gram the last
    three. A caption is flagged when either of its 3-grams occurs in more than
    one caption of the set. Captions under three words have neither and are
    counted in the denominator but never flagged. Higher is worse.
    """
    if not captions:
        return 0.0
    openers: list[tuple[str, ...] | None] = []
    closers: list[tuple[str, ...] | None] = []
    for caption in captions:
        tokens = words(caption)
        grams = word_ngrams(tokens, 3)
        openers.append(grams[0] if grams else None)
        closers.append(grams[-1] if grams else None)
    opener_counts = Counter(gram for gram in openers if gram is not None)
    closer_counts = Counter(gram for gram in closers if gram is not None)
    flagged = sum(
        1
        for opener, closer in zip(openers, closers, strict=True)
        if (opener is not None and opener_counts[opener] > 1) or (closer is not None and closer_counts[closer] > 1)
    )
    return flagged / len(captions)


def sentence_word_count_variance(captions: list[str]) -> dict[str, float]:
    """Population variance of the set's sentence counts and word counts.

    Population (divide by N, not N-1), pinned by the spec. Low variance is the
    regression: every caption the same shape is what "machine-like" looks like
    numerically.
    """
    sentence_counts = [float(_sentence_count(caption)) for caption in captions]
    word_counts = [float(len(words(caption))) for caption in captions]
    return {
        "sentence_count_variance": _population_variance(sentence_counts),
        "word_count_variance": _population_variance(word_counts),
    }


def two_sentence_emoji_rhythm_share(captions: list[str]) -> float:
    """Fraction of captions in the "exactly two sentences, then a trailing emoji" rhythm.

    The trailing emoji (and the whitespace before it) is stripped before the
    sentences are counted, so the emoji is never itself a third sentence.
    Higher is worse.
    """
    if not captions:
        return 0.0
    matches = 0
    for caption in captions:
        body, had_emoji = _strip_trailing_emoji(caption)
        if had_emoji and _sentence_count(body) == 2:
            matches += 1
    return matches / len(captions)


def tells_lexicon_hit_rate(captions: list[str], lexicon: list[str] | None = None) -> float:
    """Fraction of captions matching at least one lexicon pattern, case-insensitively.

    ``lexicon`` defaults to :data:`DEFAULT_TELLS_LEXICON`. Higher is worse.
    """
    if not captions:
        return 0.0
    patterns = [
        re.compile(pattern, re.IGNORECASE) for pattern in (lexicon if lexicon is not None else DEFAULT_TELLS_LEXICON)
    ]
    hits = sum(1 for caption in captions if any(pattern.search(caption) for pattern in patterns))
    return hits / len(captions)


def distinct_n(captions: list[str], n: int) -> float:
    """Distinct-n ratio: unique n-grams over total n-grams across the caption set.

    N-grams never cross a caption boundary. Returns 0.0 when the set yields no
    n-grams at all. Lower is worse (it means the set repeats itself).
    """
    total = 0
    unique: set[tuple[str, ...]] = set()
    for caption in captions:
        grams = word_ngrams(words(caption), n)
        total += len(grams)
        unique.update(grams)
    return len(unique) / total if total else 0.0


def tfidf_bigram_cosine(caption: str, history: list[str]) -> float:
    """Cosine similarity of ``caption``'s bigram TF-IDF vector against ``history``.

    Terms are word bigrams built per document, so bigrams never cross a document
    boundary. ``tf`` is the raw count; ``idf(t) = ln((1 + N) / (1 + df(t))) + 1``
    with N the number of history documents (smoothed, so a bigram present in
    every history document still carries weight 1.0 rather than 0). The history
    is one aggregated pseudo-document whose counts are the per-document sums.
    Both vectors are L2-normalised and the score is their dot product. An empty
    caption or an empty history scores 0.0. Higher is worse.
    """
    docs = [word_ngrams(words(document), 2) for document in history]
    docs = [grams for grams in docs if grams]
    caption_counts = Counter(word_ngrams(words(caption), 2))
    if not docs or not caption_counts:
        return 0.0

    n_docs = len(docs)
    document_frequency: Counter[tuple[str, ...]] = Counter()
    history_counts: Counter[tuple[str, ...]] = Counter()
    for grams in docs:
        history_counts.update(grams)
        document_frequency.update(set(grams))

    def _idf(term: tuple[str, ...]) -> float:
        return math.log((1 + n_docs) / (1 + document_frequency[term])) + 1.0

    caption_vector = {term: count * _idf(term) for term, count in caption_counts.items()}
    history_vector = {term: count * _idf(term) for term, count in history_counts.items()}
    caption_norm = math.sqrt(sum(value**2 for value in caption_vector.values()))
    history_norm = math.sqrt(sum(value**2 for value in history_vector.values()))
    if not caption_norm or not history_norm:
        return 0.0
    dot = sum(value * history_vector[term] for term, value in caption_vector.items() if term in history_vector)
    return dot / (caption_norm * history_norm)


def vision_field_overlap(caption: str, analysis: ImageAnalysis) -> float:
    """Share of the caption's unique content words that also appear in the analysis text.

    Content words are the caption's word tokens minus :data:`STOPWORDS`. The
    analysis side is the union of the word tokens of every descriptive field
    (:data:`_VISION_TEXT_FIELDS`). Returns 0.0 when the caption has no content
    words. Higher is worse: a caption that only replays the vision fields is a
    machine describing an image, not a voice.
    """
    content = {token for token in words(caption) if token not in STOPWORDS}
    if not content:
        return 0.0
    known = {field.name for field in dataclass_fields(analysis)}
    vision_tokens: set[str] = set()
    for name in _VISION_TEXT_FIELDS:
        if name not in known:
            continue
        value = getattr(analysis, name, None)
        if isinstance(value, str):
            vision_tokens.update(words(value))
        elif isinstance(value, list):
            for item in value:
                vision_tokens.update(words(str(item)))
    return len(content & vision_tokens) / len(content)
