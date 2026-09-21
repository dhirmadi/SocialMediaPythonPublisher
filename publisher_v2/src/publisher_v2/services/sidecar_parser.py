"""Reader for the line-oriented image sidecar format written by ``utils.captions``."""

import ast
import json
import logging
from typing import Any

from publisher_v2.utils.captions import ENCODED_STRING_MARKER
from publisher_v2.utils.logging import log_json

logger = logging.getLogger("publisher_v2.services.sidecar_parser")


def _looks_like_json(raw_value: str) -> bool:
    """Shared with the parser so the two cannot drift apart (#134 review nit)."""
    return raw_value.lstrip().startswith(("{", "["))


def _decode_json_encoded_string(raw_value: str) -> tuple[bool, str | None]:
    """``(was_marked, decoded)`` for a value carrying the encoded-string marker.

    The two are separate answers: a marked value that will not decode is
    unambiguous corruption — the file itself asserts it was encoded — so the
    caller has to report it rather than quietly keep the raw text.
    """
    if not raw_value.startswith(ENCODED_STRING_MARKER):
        return False, None
    try:
        decoded = json.loads(raw_value[len(ENCODED_STRING_MARKER) :])
    except json.JSONDecodeError:
        return True, None
    return True, decoded if isinstance(decoded, str) else None


# Only this key was ever written as a mapping, so only it can have been
# corrupted into a Python repr. Recovering any key would turn a caption whose
# text merely looks like a dict into one, and `caption` must stay a string.
_MAPPING_KEYS = frozenset({"caption_generated"})


def _recover_python_repr_mapping(raw_value: str) -> dict[str, str] | None:
    """Recover a dict the pre-#134 builder wrote with ``str()`` instead of JSON.

    Those sidecars are already on disk; the fix stops new ones being written
    but does not repair them, and every read logged a warning and dropped the
    per-platform captions. The content is a Python literal, so it is
    recoverable. ``ast.literal_eval`` evaluates no code, and the result is
    accepted only when it is a plain str-to-str mapping — the shape the builder
    could have produced — so nothing exotic is admitted.
    """
    if not (raw_value.startswith("{") and raw_value.endswith("}")):
        return None
    try:
        recovered = ast.literal_eval(raw_value)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None
    if not isinstance(recovered, dict):
        return None
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in recovered.items()):
        return None
    return recovered


def parse_sidecar_text(text: str, source: str | None = None) -> tuple[str | None, dict[str, Any] | None]:
    r"""Parse sidecar text into ``(sd_caption, metadata)``.

    The format is line-oriented: the SD prompt, a blank line, ``# ---`` and
    then ``# key: value`` lines. Values are read back as follows.

    - ``[`` or ``{`` prefix: decoded as JSON. A value that fails to decode is
      kept as raw text and logged — except for ``caption_generated``, which the
      pre-#134 builder wrote with ``str()``; that Python repr is recovered with
      ``ast.literal_eval`` when it is a plain str-to-str mapping, and the
      recovery is logged too, because the file on disk is still in the old
      shape.
    - ``!json `` prefix: a string the builder had to encode — because it spans
      lines, or because it starts with the marker itself, which keeps the
      format total. A marked value that will not decode, or that decodes to
      something other than a string, is unambiguous corruption — the file
      itself says it was encoded — so it is kept raw and logged.
    - anything else: the raw text, stripped of surrounding whitespace. A
      quoted value is NOT treated as encoded; ``"Type \n for a newline"`` is a
      legitimate caption and decodes identically to a genuine two-line value,
      which is why the marker exists.

    ``source`` names the file for the warnings; without it a corrupt sidecar is
    reported by key alone, which does not identify it among thousands.
    """
    if not text:
        return None, None

    lines = text.splitlines()
    if not lines:
        return None, None

    sd_caption = lines[0].strip() or None

    # Look for metadata header '# ---'
    meta_start = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip().startswith("# ---"):
            meta_start = idx + 1
            break

    if meta_start is None or meta_start >= len(lines):
        return sd_caption, None

    meta: dict[str, Any] = {}
    for line in lines[meta_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("# "):
            continue
        body = stripped[2:]
        if ": " not in body:
            continue
        key, raw_value = body.split(": ", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            continue
        # Try to decode JSON arrays/objects, otherwise keep as string
        was_marked, decoded_multiline = _decode_json_encoded_string(raw_value)
        if was_marked:
            if decoded_multiline is None:
                log_json(logger, logging.WARNING, "sidecar_metadata_json_invalid", key=key, source=source)
                meta[key] = raw_value
            else:
                meta[key] = decoded_multiline
            continue
        if _looks_like_json(raw_value):
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError:
                recovered = _recover_python_repr_mapping(raw_value) if key in _MAPPING_KEYS else None
                if recovered is not None:
                    # Repaired, but still reported: the file on disk is in the
                    # old broken shape until something rewrites it.
                    log_json(
                        logger,
                        logging.WARNING,
                        "sidecar_metadata_legacy_repr_recovered",
                        key=key,
                        source=source,
                    )
                    value = recovered
                else:
                    # #134: keep the raw text, but never silently — a corrupt value
                    # means data was lost upstream. Name the file: "which key" is
                    # not enough to find it among thousands.
                    log_json(logger, logging.WARNING, "sidecar_metadata_json_invalid", key=key, source=source)
                    value = raw_value
        else:
            value = raw_value
        meta[key] = value

    if not meta:
        return sd_caption, None
    return sd_caption, meta


def rehydrate_sidecar_view(text: str, source: str | None = None) -> dict[str, Any]:
    """Construct a lightweight, cache-ready view from raw sidecar text.

    Returns a dict with keys:
      - sd_caption: Optional[str]
      - caption: Optional[str] (published/edited caption from metadata; None when
        absent — NEVER the sd_caption, which is a Stable Diffusion prompt, not a
        social caption; see #80)
      - caption_submitted: Optional[dict[str, str]] (#147: the per-platform text
        the last publish run submitted, including platforms whose publish failed,
        so a retry shows the operator their own text rather than the AI's)
      - caption_generated: Optional[dict[str, str]] (per-platform generated
        captions; None when the stored value could not be read as a mapping,
        which is always reported — by `parse_sidecar_text` when the value
        failed to decode, or here when it decoded into the wrong type or was
        never decodable at all)
      - metadata: Optional[dict[str, Any]]
      - has_sidecar: bool

    This helper encapsulates canonical "sidecars as cache" semantics for the web
    layer and other callers that do not need a full ImageAnalysis instance.
    """
    sd_caption, metadata = parse_sidecar_text(text, source=source)
    caption: str | None = None
    caption_generated: dict[str, Any] | None = None
    if isinstance(metadata, dict):
        raw_caption = metadata.get("caption")
        if isinstance(raw_caption, str):
            raw_caption = raw_caption.strip()
            if raw_caption:
                caption = raw_caption
        raw_generated = metadata.get("caption_generated")
        if isinstance(raw_generated, dict):
            caption_generated = raw_generated
        elif raw_generated is not None and not (isinstance(raw_generated, str) and not raw_generated.strip()):
            # Anything that WOULD parse into a mapping has already been decoded
            # into one above, so reaching here means the value is lost: a plain
            # string, or something that decoded cleanly but is not a mapping
            # (a JSON list, say). Only this layer knows the key must hold a
            # mapping, so only this layer can report those.
            #
            # The parser warns when a value FAILED to decode, so warning again
            # for those would double-report. It cannot have warned for a value
            # that never looked decodable, or for one that decoded fine into
            # the wrong type — which is exactly what is left here.
            # Derived from the value's shape rather than from what the parser
            # actually did, which is where this is imprecise: a MARKED value
            # that decodes into a string itself starting with `{`, `[` or the
            # marker is suppressed here and lost silently. That needs a
            # hand-edited sidecar — the writer only ever stores a mapping under
            # this key — so it is left as a known limit rather than threading
            # the parser's warning set through the return type.
            parser_already_warned = isinstance(raw_generated, str) and (
                _looks_like_json(raw_generated) or raw_generated.startswith(ENCODED_STRING_MARKER)
            )
            if not parser_already_warned:
                log_json(
                    logger,
                    logging.WARNING,
                    "sidecar_metadata_json_invalid",
                    key="caption_generated",
                    source=source,
                )
            caption_generated = None
    # #147: what each platform actually received, when a publish recorded it.
    # Additive and separate from caption_generated (the AI's own output), so an
    # operator's per-platform edits survive and are what the UI shows back.
    caption_submitted: dict[str, Any] | None = None
    if isinstance(metadata, dict):
        raw_published = metadata.get("caption_submitted")
        if isinstance(raw_published, dict):
            caption_submitted = raw_published
        elif raw_published is not None and not (isinstance(raw_published, str) and not raw_published.strip()):
            parser_already_warned = isinstance(raw_published, str) and (
                _looks_like_json(raw_published) or raw_published.startswith(ENCODED_STRING_MARKER)
            )
            if not parser_already_warned:
                log_json(
                    logger,
                    logging.WARNING,
                    "sidecar_metadata_json_invalid",
                    key="caption_submitted",
                    source=source,
                )
    has_sidecar = bool(sd_caption or metadata)
    return {
        "sd_caption": sd_caption,
        "caption": caption,
        "caption_generated": caption_generated,
        "caption_submitted": caption_submitted,
        "metadata": metadata,
        "has_sidecar": has_sidecar,
    }
