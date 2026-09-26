"""Caption sidecar generation and updates in storage.

A sidecar is the ``.txt`` file written beside each image; it carries the SD
prompt, the per-platform captions and the provenance metadata (image identity,
model version, Dropbox file id/rev) that caption history and later web Analyze
calls read back. Both entry points return their duration in milliseconds (the
caption update alongside the sidecar view it read) and report failures through structured logs rather than raising, so a sidecar
problem never aborts a publish.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any, NamedTuple

from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view
from publisher_v2.services.storage_protocol import StorageProtocol
from publisher_v2.utils.captions import (
    build_caption_sidecar,
    build_metadata_phase1,
    build_metadata_phase2,
)
from publisher_v2.utils.logging import elapsed_ms, log_json, now_monotonic

logger = logging.getLogger("publisher_v2.services.sidecar")


async def generate_and_upload_sidecar(
    storage: StorageProtocol,
    config: ApplicationConfig,
    filename: str,
    analysis: ImageAnalysis,
    sd_caption: str,
    model_version: str,
    sha256: str = "",
    correlation_id: str | None = None,
    log_prefix: str = "sidecar_upload",
    caption_generated: str | None = None,
    caption_edited: bool = False,
    platform_captions: dict[str, str] | None = None,
    caption_angles: dict[str, str] | None = None,
    sd_caption_version: str | None = None,
) -> float:
    """Generate and upload a caption sidecar file.

    ``platform_captions`` (#80): the per-platform social captions generated in
    this run; persisted as a ``caption_generated`` JSON dict so later web
    Analyze calls can serve the real caption instead of the SD prompt.
    ``caption_angles`` (PUB-051): platform -> the content-angle key each of
    those captions was written under; metadata only, never shown as a caption.
    ``sd_caption_version`` (PUB-051): the version recorded for a kept SD prompt;
    None means "v1.0" when there is an SD prompt and nothing otherwise.

    Returns:
        float: Duration of the operation in milliseconds.
    """
    start_time = now_monotonic()

    try:
        created_iso = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        # 1. Get file metadata from Dropbox for ID/Rev linkage
        file_meta = await storage.get_file_metadata(config.storage_paths.image_folder, filename)

        # 2. Build metadata
        phase1 = build_metadata_phase1(
            image_file=filename,
            sha256=sha256,
            created_iso=created_iso,
            # PUB-051: no SD prompt, no SD version; a kept SD prompt keeps its recorded version.
            sd_caption_version=sd_caption_version if sd_caption_version is not None else ("v1.0" if sd_caption else ""),
            model_version=model_version,
            dropbox_file_id=file_meta.file_id,
            dropbox_rev=file_meta.revision,
            artist_alias=config.captionfile.artist_alias,
        )
        meta = dict(phase1)

        if config.captionfile.extended_metadata_enabled and analysis:
            phase2 = build_metadata_phase2(analysis)
            meta.update(phase2)

        # PUB-035: Store edit tracking metadata
        if platform_captions and not caption_generated:
            caption_generated = json.dumps(platform_captions, ensure_ascii=False)
        if caption_generated:
            meta["caption_generated"] = caption_generated
        if caption_angles:
            meta["caption_angles"] = dict(caption_angles)
        if caption_edited:
            meta["caption_edited"] = str(caption_edited)
            # #147: this writes the SD prompt under the `caption` + `caption_edited`
            # pair that the web layer reads back as "an operator caption was
            # published" and shows in every platform editor. No production caller
            # passes caption_edited here today; wiring one up would put the SD
            # prompt in front of the operator as a caption (the #80 regression).
            meta["caption"] = sd_caption  # published version

        # 3. Build content
        content = build_caption_sidecar(sd_caption, meta)

        # 4. Upload
        log_json(logger, logging.INFO, f"{log_prefix}_start", image=filename, correlation_id=correlation_id)

        await storage.write_sidecar_text(config.storage_paths.image_folder, filename, content)

        duration = elapsed_ms(start_time)

        log_json(
            logger,
            logging.INFO,
            f"{log_prefix}_complete",
            image=filename,
            correlation_id=correlation_id,
            sidecar_write_ms=duration,
        )
        return duration

    except Exception as exc:
        duration = elapsed_ms(start_time)
        log_json(
            logger,
            logging.ERROR,
            f"{log_prefix}_error",
            image=filename,
            error=str(exc),
            correlation_id=correlation_id,
            sidecar_write_ms=duration,
        )
        raise


class ExistingSdLine(NamedTuple):
    """PUB-051: an SD prompt already on a sidecar's line 1, with the metadata recorded for it."""

    sd_caption: str
    sd_caption_version: str
    model_version: str


async def read_existing_sd_line(
    storage: StorageProtocol,
    folder: str,
    filename: str,
    correlation_id: str | None = None,
) -> ExistingSdLine | None:
    """PUB-051: the SD prompt on ``filename``'s existing sidecar, or None when there is none.

    A run that writes a sidecar with no new SD prompt keeps this one rather than
    blanking line 1. Fail-safe: a read or parse failure returns None and logs a
    content-free warning.
    """
    try:
        blob = await storage.download_sidecar_if_exists(folder, filename)
        if not blob:
            return None
        view = rehydrate_sidecar_view(blob.decode("utf-8", errors="replace"), source=filename)
    except Exception:
        log_json(logger, logging.WARNING, "sidecar_sd_line_read_failed", image=filename, correlation_id=correlation_id)
        return None
    sd_line = str(view.get("sd_caption") or "").strip()
    if not sd_line:
        return None
    meta = view.get("metadata") or {}
    return ExistingSdLine(
        sd_caption=sd_line,
        sd_caption_version=str(meta.get("sd_caption_version") or ""),
        model_version=str(meta.get("model_version") or ""),
    )


class SidecarCaptionUpdate(NamedTuple):
    """Result of ``update_sidecar_with_caption``.

    ``prior_view`` is the rehydrated view (``rehydrate_sidecar_view``) of the
    sidecar as it was before this update, or None when there was none. PUB-051
    reads the override angles from it, so an override publish downloads the
    sidecar only once.
    """

    duration_ms: float
    prior_view: dict[str, Any] | None


async def update_sidecar_with_caption(
    storage: StorageProtocol,
    folder: str,
    filename: str,
    published_caption: str,
    caption_edited: bool = True,
    correlation_id: str | None = None,
    published_platform_captions: dict[str, str] | None = None,
) -> SidecarCaptionUpdate:
    """Update an existing sidecar with the published caption.

    PUB-035: When a caption override is used, the published caption must be
    recorded in the sidecar so caption history works correctly.

    If no sidecar exists, creates a minimal one with just the caption.

    Returns:
        SidecarCaptionUpdate: the duration in milliseconds and the view of the
        sidecar as read before the update (None when none existed).
    """
    start_time = now_monotonic()

    try:
        log_json(
            logger,
            logging.INFO,
            "sidecar_caption_update_start",
            image=filename,
            correlation_id=correlation_id,
        )

        existing_data = await storage.download_sidecar_if_exists(folder, filename)

        sd_caption: str | None = None
        meta: dict[str, Any] = {}
        prior_view: dict[str, Any] | None = None

        if existing_data:
            text = existing_data.decode("utf-8", errors="replace")
            prior_view = rehydrate_sidecar_view(text, source=filename)
            sd_caption = prior_view.get("sd_caption")
            parsed_meta = prior_view.get("metadata")
            if parsed_meta:
                meta = dict(parsed_meta)

        meta["caption"] = published_caption
        # #147: the per-platform text this run submitted to the publishers, under
        # its own additive key. ``caption`` can only hold one text and
        # ``caption_generated`` is the AI's output — overwriting either would lose
        # the operator's per-platform edits, which is what the web UI reads back.
        #
        # "submitted", not "published": the sidecar is written once per run, when
        # any platform succeeded, so a platform that failed is recorded too. That
        # is deliberate — a retry must show the operator the text they wrote, not
        # the AI's original — and is why the key is not named for publication.
        if published_platform_captions:
            meta["caption_submitted"] = dict(published_platform_captions)
        meta["caption_edited"] = str(caption_edited)
        meta["caption_updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        # PUB-051: line 1 is the SD prompt slot. It keeps the existing SD prompt or
        # stays empty; the social caption is never moved into it.
        content = build_caption_sidecar(sd_caption or "", meta)

        await storage.write_sidecar_text(folder, filename, content)

        duration = elapsed_ms(start_time)
        log_json(
            logger,
            logging.INFO,
            "sidecar_caption_update_complete",
            image=filename,
            correlation_id=correlation_id,
            sidecar_caption_update_ms=duration,
        )
        return SidecarCaptionUpdate(duration, prior_view)

    except Exception as exc:
        duration = elapsed_ms(start_time)
        log_json(
            logger,
            logging.ERROR,
            "sidecar_caption_update_error",
            image=filename,
            error=str(exc),
            correlation_id=correlation_id,
            sidecar_caption_update_ms=duration,
        )
        raise
