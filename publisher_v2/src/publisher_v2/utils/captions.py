import json
import re
from typing import Any

from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.models import ImageAnalysis


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

    out = re.sub(r"#\w+", _replace, text)
    # Collapse the whitespace gaps left by removed duplicates / overflow tokens.
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.rstrip()


def normalize_tags(raw: list[str], max_count: int) -> list[str]:
    """
    Clean and deduplicate tag strings: strip whitespace, lowercase,
    remove leading '#', collapse non-alphanum chars, and limit count.
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
    "email": 240,  # FetLife email path: keep within ~240 to avoid truncation
    "generic": 2200,
}


def _trim_to_length(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    # Favor keeping full hashtags at the end; truncate before trailing hashtags if possible
    parts = re.split(r"(\s#)", text)
    base = parts[0]
    if len(base) + 1 <= max_len:
        return (base[: max_len - 1]).rstrip() + "…"
    return text[: max_len - 1].rstrip() + "…"


def _limit_instagram_hashtags(text: str, max_hashtags: int) -> str:
    hashtags = re.findall(r"#\w+", text)
    if len(hashtags) <= max_hashtags:
        return text
    # Keep the first N, remove extras
    keep = set(hashtags[:max_hashtags])

    def repl(m):
        return m.group(0) if m.group(0) in keep else ""

    text = re.sub(r"#\w+", repl, text)
    # Normalize spaces
    return re.sub(r"\s{2,}", " ", text).strip()


def _sanitize_for_fetlife(text: str) -> str:
    """
    Normalize punctuation and unicode that FetLife may strip, to preserve spacing and readability.
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
    p = platform.lower()
    static_limits = get_static_config().platform_limits
    if p == "instagram":
        max_len = static_limits.instagram.max_caption_length or _MAX_LEN["instagram"]
        max_hashtags = static_limits.instagram.max_hashtags or 30
    elif p == "telegram":
        max_len = static_limits.telegram.max_caption_length or _MAX_LEN["telegram"]
        max_hashtags = None
    elif p == "email":
        max_len = static_limits.email.max_caption_length or _MAX_LEN["email"]
        max_hashtags = None
    else:
        max_len = static_limits.generic.max_caption_length or _MAX_LEN["generic"]
        max_hashtags = None
    formatted = caption.strip()
    # PUB-028: clean AI-generated hashtags before platform-specific processing.
    # Email strips all hashtags below, so the normalization is a no-op there.
    if smart_hashtags:
        formatted = normalize_generated_hashtags(formatted, max_count=max_hashtags or 30)
    if p == "instagram":
        formatted = _limit_instagram_hashtags(formatted, max_hashtags or 30)
    elif p == "email":
        # FetLife email path: strip all hashtags entirely
        formatted = re.sub(r"#\w+", "", formatted)
        formatted = _sanitize_for_fetlife(formatted)
    # Telegram can keep as-is (supports 4096 chars)
    formatted = _trim_to_length(formatted, max_len)
    return formatted


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
    """
    Build Phase 1 identity/version metadata. Omit missing fields.
    """
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


def build_metadata_phase2(analysis: ImageAnalysis) -> dict[str, Any]:
    """
    Build Phase 2 contextual metadata from analysis. Omit missing/empty fields.
    """
    meta: dict[str, Any] = {}
    # Core contextual fields
    if getattr(analysis, "subject", None):
        meta["subject"] = analysis.subject
    if getattr(analysis, "lighting", None):
        meta["lighting"] = analysis.lighting
    if getattr(analysis, "pose", None):
        meta["pose"] = analysis.pose
    if getattr(analysis, "camera", None):
        meta["camera"] = analysis.camera
    # Map 'materials' to clothing_or_accessories if present
    materials = getattr(analysis, "clothing_or_accessories", None)
    if materials:
        meta["materials"] = materials
    if getattr(analysis, "style", None):
        meta["art_style"] = analysis.style
    if getattr(analysis, "composition", None):
        meta["composition"] = analysis.composition
    if getattr(analysis, "background", None):
        meta["background"] = analysis.background
    if getattr(analysis, "color_palette", None):
        meta["color_palette"] = analysis.color_palette
    if getattr(analysis, "alt_text", None):
        meta["alt_text"] = analysis.alt_text
    if getattr(analysis, "distinctive_detail", None):
        meta["distinctive_detail"] = analysis.distinctive_detail
    tags = getattr(analysis, "tags", None) or []
    if isinstance(tags, list) and tags:
        meta["tags"] = [str(t) for t in tags if str(t).strip()]
    aesthetics = getattr(analysis, "aesthetic_terms", None) or []
    if isinstance(aesthetics, list) and aesthetics:
        meta["aesthetic_terms"] = [str(a) for a in aesthetics if str(a).strip()]
    moderation = getattr(analysis, "safety_labels", None) or []
    if isinstance(moderation, list) and moderation:
        meta["moderation"] = [str(m) for m in moderation if str(m).strip()]
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
    """
    Compose the sidecar file content:
    - First line: sd_caption
    - Blank line
    - '# ---'
    - '# key: value' lines; arrays and objects encoded as JSON (#134: a dict via str()
      became a Python repr that the parser could not read back)
    - a string that spans lines is written as `!json "<json string>"`. The
      format is one line per key, so an unencoded multi-line value loses
      everything after its first line, and "spans lines" means any character
      `str.splitlines()` splits on, not just `\n`. The marker is explicit
      because a quoted value is otherwise ambiguous: `"Type \\n for a newline"`
      is a valid single-line caption that decodes exactly like a two-line one.
      A string that merely starts with the marker is encoded too, so the
      format is total. Every other single-line string is written bare, so
      existing sidecars keep their current shape.
    """
    lines: list[str] = []
    lines.append(sd_caption.strip())
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


def _words(text: str) -> list[str]:
    """Lowercased word tokens, punctuation-insensitive."""
    return _WORD_RE.findall(text.lower())


def trigram_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of the word-trigram sets of two captions (#82).

    Texts shorter than three words fall back to word-set Jaccard so very
    short captions still compare meaningfully. Returns a float in [0, 1].
    """
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    if len(wa) < 3 or len(wb) < 3:
        sa, sb = set(wa), set(wb)
        return len(sa & sb) / len(sa | sb)
    ta = {tuple(wa[i : i + 3]) for i in range(len(wa) - 2)}
    tb = {tuple(wb[i : i + 3]) for i in range(len(wb) - 2)}
    return len(ta & tb) / len(ta | tb)


# Ordered registry: order is the deterministic tie-break for least-recently-used.
STRUCTURE_DIRECTIVES: dict[str, str] = {
    "declarative": "Open with a plain declarative statement.",
    "fragment": "Open with a short sensory fragment (no full sentence needed).",
    "second_person": "Address the viewer directly in second person.",
    "observation": "Write a quiet observation; no questions anywhere in the caption.",
    "short_line": "Write a single line under 12 words.",
}


def classify_caption_structure(caption: str) -> str:
    """Best-effort mapping of a caption to a STRUCTURE_DIRECTIVES key.

    Approximate by design — it only needs to be stable enough for the
    least-recently-used rotation in ``pick_structure_directive``.
    """
    stripped = caption.strip().strip('"')
    words = _words(stripped)
    lowered = stripped.lower()
    if lowered.startswith(("you ", "your ", "you'")):
        return "second_person"
    first_sentence = re.split(r"[.!?\n]", stripped, maxsplit=1)[0]
    if len(_words(first_sentence)) <= 4:
        return "fragment"
    if len(words) < 8 and "\n" not in stripped:
        return "short_line"
    sentence_count = len([s for s in re.split(r"[.!?\n]+", stripped) if s.strip()])
    if "?" not in stripped and sentence_count >= 2:
        return "observation"
    return "declarative"


def pick_structure_directive(history: list[str], exclude: frozenset[str] = frozenset()) -> str:
    """Pick the structural directive least recently used in ``history`` (#82).

    ``history`` is ordered most-recent-first (as fetched from the DB). The
    directive whose structure appears furthest back (or not at all) wins;
    registry order breaks ties deterministically. ``exclude`` (#138) removes
    directive keys that would contradict the platform brief.
    """
    candidates = [k for k in STRUCTURE_DIRECTIVES if k not in exclude] or list(STRUCTURE_DIRECTIVES)
    last_used: dict[str, int] = {}
    for idx, caption in enumerate(history):
        key = classify_caption_structure(caption)
        if key not in last_used:
            last_used[key] = idx  # smaller idx == more recent
    never_used = [k for k in candidates if k not in last_used]
    if never_used:
        return STRUCTURE_DIRECTIVES[never_used[0]]
    key = max(candidates, key=lambda k: last_used[k])
    return STRUCTURE_DIRECTIVES[key]


def caption_opening(caption: str, word_count: int = 6) -> str:
    """First ``word_count`` words of a caption, for openings-to-avoid lists."""
    return " ".join(caption.strip().strip('"').split()[:word_count])


def caption_closing_pattern(caption: str) -> str:
    """Classify how a caption closes: question | statement | fragment."""
    stripped = caption.strip().strip('"')
    if stripped.endswith("?"):
        return "question"
    if stripped.endswith((".", "!")):
        return "statement"
    return "fragment"
