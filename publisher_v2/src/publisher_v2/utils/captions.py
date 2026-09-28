"""Caption formatting, tag normalization and the image sidecar writer."""

import json
import re
from collections.abc import Sequence
from typing import Any

from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.models import ImageAnalysis

_HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)

# The base emoji character class shared with ``utils.caption_metrics``: arrows and
# symbols, misc technical through dingbats, misc symbols and arrows, and the
# pictograph planes. Callers compose their own class from it (bracket-less, so it
# can be dropped into a larger ``[...]``).
EMOJI_BASE_CHARS = "\u2190-\u21ff\u2300-\u27bf\u2b00-\u2bff\U0001f000-\U0001faff"
# Variation selectors U+FE00-U+FE0F.
EMOJI_VARIATION_SELECTORS = "\ufe00-\ufe0f"


def normalize_generated_hashtags(text: str, max_count: int = 30) -> str:
    """Normalize AI-generated hashtags inside ``text`` (PUB-028).

    Lowercases each ``#tag`` token, deduplicates while preserving first-seen
    order, and caps the total at ``max_count``. Tokens beyond the cap (and any
    duplicates) are removed from the output. Non-hashtag text is preserved.
    """
    seen: dict[str, str] = {}

    def _replace(match: re.Match[str]) -> str:
        original = match.group(0)
        lower = original.lower()
        if lower in seen:
            return ""
        if len(seen) >= max(0, max_count):
            return ""
        seen[lower] = lower
        return lower

    out = _HASHTAG_RE.sub(_replace, text)
    # Collapse the whitespace gaps left by removed duplicates / overflow tokens.
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.rstrip()


def normalize_tags(raw: list[str], max_count: int) -> list[str]:
    """Clean and deduplicate tag strings.

    Strip whitespace, lowercase, remove leading '#', collapse non-alphanum
    chars, and limit count. Order of first appearance is preserved and a
    negative ``max_count`` yields an empty list.
    """
    cleaned: list[str] = []
    for t in raw:
        t = t.strip().lower().lstrip("#")
        t = "".join(ch if ch.isalnum() or ch == " " else " " for ch in t)
        t = " ".join(t.split())
        if t and t not in cleaned:
            cleaned.append(t)
    return cleaned[: max(0, max_count)]


_MAX_LEN = {
    "instagram": 2200,
    "telegram": 4096,
    "email": 240,  # FetLife subject limit, measured 2026-09-27 (#146)
    "generic": 2200,
}


def smart_truncate(text: str, max_length: int, ellipsis: str = "…") -> str:
    """Truncate text to max_length while respecting word boundaries.

    Tries to cut at sentence end (. ! ?) first, then at word boundary.
    A sentence-end cut needs no ellipsis — the text ends where a sentence does.
    A word-boundary cut appends one, and only that path reserves room for it.
    """
    if len(text) <= max_length:
        return text

    # #138: a cut at a sentence end needs no ellipsis, so search the full budget
    # for one first (a sentence end is followed by a space in the original text).
    for i in range(max_length - 1, -1, -1):
        if text[i] in ".!?" and (i + 1 >= len(text) or text[i + 1] == " "):
            return text[: i + 1]

    # Leave room for ellipsis
    target_len = max_length - len(ellipsis)
    if target_len <= 0:
        return ellipsis[:max_length]

    truncated = text[:target_len]

    # Fall back to word boundary - find last space
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space].rstrip(".,;:!?-") + ellipsis

    # No good boundary found, just cut
    return truncated.rstrip() + ellipsis


def platform_caption_limit(platform: str) -> int:
    """The hard caption length for ``platform`` from static config (unknown platforms use generic)."""
    p = platform.lower()
    limits = get_static_config().platform_limits
    spec = getattr(limits, p) if p in type(limits).model_fields else limits.generic
    key = p if p in _MAX_LEN else "generic"
    return spec.max_caption_length or _MAX_LEN[key]


def _limit_instagram_hashtags(text: str, max_hashtags: int) -> str:
    hashtags = _HASHTAG_RE.findall(text)
    if len(hashtags) <= max_hashtags:
        return text
    # Keep the first N, remove extras
    keep = set(hashtags[:max_hashtags])

    def repl(m):
        return m.group(0) if m.group(0) in keep else ""

    text = _HASHTAG_RE.sub(repl, text)
    # Normalize spaces
    return re.sub(r"\s{2,}", " ", text).strip()


def _sanitize_for_fetlife(text: str) -> str:
    """Normalize punctuation and unicode that FetLife may strip.

    Preserves spacing and readability on the FetLife email path.

    Examples:
      - em/en dashes → ' - ' so 'trust—what' becomes 'trust - what'
      - smart quotes → ASCII quotes
      - ellipsis char → '...'
      - collapse any excessive whitespace after replacements
    """
    # Dashes: em (—), en (–), minus (−)
    text = re.sub(r"[—–−]", " - ", text)
    # Smart quotes
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # Ellipsis
    text = text.replace("…", "...")
    # Zero-width and non-breaking spaces to regular space
    text = text.replace("\u200b", " ").replace("\u00a0", " ")
    # Collapse multiple spaces created by replacements
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def format_caption(platform: str, caption: str, smart_hashtags: bool = False) -> str:
    """Apply the platform's caption rules and return the text ready to publish.

    Instagram caps the hashtag count; email (the FetLife path) strips hashtags
    entirely and normalizes punctuation; Telegram is left as-is. Any unknown
    platform falls back to the generic limits. The result is trimmed to the
    platform maximum by ``smart_truncate`` (a sentence end, else a word boundary
    plus an ellipsis); the limit wins over keeping trailing hashtags (#281).

    Args:
        platform: Platform name, matched case-insensitively.
        caption: Raw caption text.
        smart_hashtags: Normalize AI-generated hashtags first (PUB-028); a
            no-op for email, which strips hashtags anyway.
    """
    p = platform.lower()
    max_len = platform_caption_limit(p)
    max_hashtags = (get_static_config().platform_limits.instagram.max_hashtags or 30) if p == "instagram" else None
    formatted = caption.strip()
    # PUB-028: clean AI-generated hashtags before platform-specific processing.
    # Email strips all hashtags below, so the normalization is a no-op there.
    if smart_hashtags:
        formatted = normalize_generated_hashtags(formatted, max_count=max_hashtags or 30)
    if p == "instagram":
        formatted = _limit_instagram_hashtags(formatted, max_hashtags or 30)
    elif p == "email":
        # FetLife email path: strip all hashtags entirely
        formatted = _HASHTAG_RE.sub("", formatted)
        formatted = _sanitize_for_fetlife(formatted)
    # Telegram can keep as-is (supports 4096 chars)
    # #281: the hard limit wins over keeping trailing hashtags.
    # FetLife is ASCII-only, so the email path truncates with "..." not "…".
    return smart_truncate(formatted, max_len, ellipsis="..." if p == "email" else "…")


def build_metadata_phase1(
    image_file: str,
    sha256: str,
    created_iso: str,
    sd_caption_version: str,
    model_version: str,
    dropbox_file_id: str | None,
    dropbox_rev: str | None,
    artist_alias: str | None = None,
) -> dict[str, Any]:
    """Build Phase 1 identity/version metadata. Omit missing fields."""
    meta: dict[str, Any] = {}
    if image_file:
        meta["image_file"] = image_file
    # #96: backend-agnostic identity keys. The legacy dropbox_* keys stay for
    # sidecar compatibility (fields are additive-only per the sidecar rules).
    if dropbox_file_id:
        meta["dropbox_file_id"] = dropbox_file_id
        meta["file_id"] = dropbox_file_id
    if dropbox_rev:
        meta["dropbox_rev"] = dropbox_rev
        meta["revision"] = dropbox_rev
    if sha256:
        meta["sha256"] = sha256
    if created_iso:
        meta["created"] = created_iso
    if sd_caption_version:
        meta["sd_caption_version"] = sd_caption_version
    if model_version:
        meta["model_version"] = model_version
    if artist_alias:
        meta["artist_alias"] = artist_alias
    return meta


# (ImageAnalysis field, sidecar key) in output order. ``materials`` and
# ``art_style`` are the sidecar names for ``clothing_or_accessories`` and ``style``.
_PHASE2_TEXT_FIELDS: tuple[tuple[str, str], ...] = (
    ("subject", "subject"),
    ("lighting", "lighting"),
    ("pose", "pose"),
    ("camera", "camera"),
    ("clothing_or_accessories", "materials"),
    ("style", "art_style"),
    ("composition", "composition"),
    ("background", "background"),
    ("color_palette", "color_palette"),
    ("alt_text", "alt_text"),
    ("distinctive_detail", "distinctive_detail"),
)
_PHASE2_LIST_FIELDS: tuple[tuple[str, str], ...] = (
    ("tags", "tags"),
    ("aesthetic_terms", "aesthetic_terms"),
    ("safety_labels", "moderation"),
)


def _clean_str_list(values: list[Any]) -> list[str]:
    """Stringify ``values``, dropping entries that are blank once stripped."""
    return [str(v) for v in values if str(v).strip()]


def build_metadata_phase2(analysis: ImageAnalysis) -> dict[str, Any]:
    """Build Phase 2 contextual metadata from analysis. Omit missing/empty fields."""
    meta: dict[str, Any] = {}
    for field, key in _PHASE2_TEXT_FIELDS:
        value = getattr(analysis, field, None)
        if value:
            meta[key] = value
    for field, key in _PHASE2_LIST_FIELDS:
        values = getattr(analysis, field, None) or []
        if isinstance(values, list) and values:
            meta[key] = _clean_str_list(values)
    return meta


# Everything str.splitlines() splits on. Checking for "\n" alone left a value
# containing \r or U+2028 truncated at that character, silently.
LINE_BREAKS = "\n\r\x0b\x0c\x85\u2028\u2029"

# Prefix for a string value the builder had to JSON-encode. Explicit because
# the encoding is otherwise indistinguishable from a caption that quotes itself
# and mentions a backslash escape: `"Type \\n for a newline"` decodes to the
# same thing as a genuinely two-line value.
ENCODED_STRING_MARKER = "!json "


def _escape_line_breaks(rendered: str) -> str:
    """json.dumps(ensure_ascii=False) leaves these raw, and splitlines() splits on them."""
    for ch in LINE_BREAKS:
        if ch in rendered:
            rendered = rendered.replace(ch, f"\\u{ord(ch):04x}")
    return rendered


def build_caption_sidecar(sd_caption: str, metadata: dict[str, Any]) -> str:
    r"""Compose the sidecar file content.

    - First line: sd_caption, flattened to one line (every whitespace run, line
      breaks included, becomes one space) so it cannot inject `# key: value` lines
    - Blank line
    - '# ---'
    - '# key: value' lines; arrays and objects encoded as JSON (#134: a dict via str()
      became a Python repr that the parser could not read back)
    - a string that spans lines is written as `!json "<json string>"`. The
      format is one line per key, so an unencoded multi-line value loses
      everything after its first line, and "spans lines" means any character
      `str.splitlines()` splits on, not just `\n`. The marker is explicit
      because a quoted value is otherwise ambiguous: `"Type \n for a newline"`
      is a valid single-line caption that decodes exactly like a two-line one.
      A string that merely starts with the marker is encoded too, so the
      format is total. Every other single-line string is written bare, so
      existing sidecars keep their current shape.
    """
    lines: list[str] = []
    lines.append(" ".join(sd_caption.split()))
    lines.append("")  # blank line
    lines.append("# ---")
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, list | dict):
            rendered = _escape_line_breaks(json.dumps(value, ensure_ascii=False))
        elif isinstance(value, str) and (
            any(ch in value for ch in LINE_BREAKS) or value.startswith(ENCODED_STRING_MARKER)
        ):
            # Marked, so the parser never has to guess whether a quoted value
            # was encoded or is simply a caption containing quotes.
            rendered = ENCODED_STRING_MARKER + _escape_line_breaks(json.dumps(value, ensure_ascii=False))
        else:
            rendered = str(value)
        lines.append(f"# {key}: {rendered}")
    lines.append("")  # trailing newline
    return "\n".join(lines)


# --- #82 (CAP-5/CAP-6): caption diversity helpers ---

# #144: [^\W_] is "word character but not underscore", so accented letters stay
# inside their word instead of splitting it ("café" was "caf" + a dropped tail).
_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)


def words(text: str) -> list[str]:
    """Lowercased word tokens, punctuation-insensitive.

    PUB-049: this is the single tokenizer for every caption metric in the
    codebase. ``utils/caption_metrics.py`` imports it rather than keeping a
    second definition of "how a caption tokenizes into words".
    """
    return _WORD_RE.findall(text.lower())


# Kept as the historical private name; ``words`` is the public spelling (PUB-049).
_words = words


def word_ngrams(tokens: Sequence[str], n: int) -> list[tuple[str, ...]]:
    """Return the ordered word n-grams of ``tokens`` (empty when too short).

    PUB-049: the one n-gram construction shared by ``trigram_jaccard`` and the
    opener/closer, distinct-n and TF-IDF bigram metrics.
    """
    if n <= 0 or len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def trigram_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of the word-trigram sets of two captions (#82).

    Texts shorter than three words fall back to word-set Jaccard so very
    short captions still compare meaningfully. Returns a float in [0, 1].
    """
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    if len(wa) < 3 or len(wb) < 3:
        sa, sb = set(wa), set(wb)
        return len(sa & sb) / len(sa | sb)
    ta, tb = set(word_ngrams(wa, 3)), set(word_ngrams(wb, 3))
    return len(ta & tb) / len(ta | tb)


# PUB-051: the content-angle pool. Each directive names what the caption dwells
# on, not how it opens. Ordered: order is the deterministic LRU tie-break. No
# directive text may contain another, so a prompt can be counted structurally.
# AC9 follow-up: no scene words (after/before) or nouns the model copies as an
# opener ("air") -- "after the shot" came back as "After the session...".
CONTENT_ANGLES: dict[str, str] = {
    "sensation": "Topic: one physical sensation.",
    "moment": "Topic: what the camera did not see.",
    "detail": "Topic: one overlooked detail.",
    "craft": "Topic: a decision behind the picture.",
    "atmosphere": "Topic: the sound and temperature of the space.",
    "direct_address": "Topic: the reader, spoken to directly.",
}


def angle_history_depth(window_size: int) -> int:
    """How many stored angles per platform the rotation reads (PUB-051).

    At least the pool size, so a caption-history window smaller than the pool
    cannot starve the least recently used angles.
    """
    return max(window_size, len(CONTENT_ANGLES))


def pick_content_angle(
    history_angles: Sequence[str | None],
    exclude: frozenset[str] = frozenset(),
    avoid: frozenset[str] = frozenset(),
) -> str:
    """Pick the content-angle key least recently used in ``history_angles`` (PUB-051).

    ``history_angles`` holds the stored ``angle`` of each history row,
    most-recent-first. ``None`` (a row written before the column existed) and
    keys no longer in the pool count as never used. Never-used keys win, in pool
    order; otherwise the key used furthest back wins. ``exclude`` removes keys
    that would contradict the platform brief; excluding everything falls back to
    the whole pool rather than failing. ``avoid`` is a soft preference (keys
    already taken by other platforms in the same call): the first key in LRU
    order that is not avoided wins, and when every candidate is avoided the plain
    LRU pick is returned.
    """
    candidates = [k for k in CONTENT_ANGLES if k not in exclude] or list(CONTENT_ANGLES)
    last_used: dict[str, int] = {}
    for idx, key in enumerate(history_angles):
        if key in CONTENT_ANGLES and key not in last_used:
            last_used[key] = idx  # smaller idx == more recent
    never_used = [k for k in candidates if k not in last_used]
    used = sorted((k for k in candidates if k in last_used), key=lambda k: -last_used[k])
    ranked = never_used + used
    return next((k for k in ranked if k not in avoid), ranked[0])


def caption_opening(caption: str, word_count: int = 6) -> str:
    """First ``word_count`` words of a caption, for openings-to-avoid lists."""
    return " ".join(caption.strip().strip('"').split()[:word_count])


# Pictographs, dingbats, arrows/symbols blocks, variation selectors and the ZWJ.
_EMOJI_RE = re.compile(f"[{EMOJI_BASE_CHARS}{EMOJI_VARIATION_SELECTORS}\u200d]")


def strip_emoji_and_hashtags(caption: str) -> str:
    """PUB-051: a history caption without its emoji and hashtags, whitespace collapsed.

    Constraints are derived from the words; an opening such as "🌿 #shibari
    Window light" must not teach the model to avoid an emoji.
    """
    return " ".join(_EMOJI_RE.sub(" ", _HASHTAG_RE.sub(" ", caption)).split())
