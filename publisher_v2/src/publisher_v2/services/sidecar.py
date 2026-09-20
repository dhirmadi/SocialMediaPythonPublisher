import json
import logging
from datetime import UTC, datetime
from typing import Any

from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.sidecar_parser import parse_sidecar_text
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
) -> float:
    """
    Generate and upload a caption sidecar file.

    ``platform_captions`` (#80): the per-platform social captions generated in
    this run; persisted as a ``caption_generated`` JSON dict so later web
    Analyze calls can serve the real caption instead of the SD prompt.

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
            sd_caption_version="v1.0",
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


async def update_sidecar_with_caption(
    storage: StorageProtocol,
    folder: str,
    filename: str,
    published_caption: str,
    caption_edited: bool = True,
    correlation_id: str | None = None,
    published_platform_captions: dict[str, str] | None = None,
) -> float:
    """
    Update an existing sidecar with the published caption.

    PUB-035: When a caption override is used, the published caption must be
    recorded in the sidecar so caption history works correctly.

    If no sidecar exists, creates a minimal one with just the caption.

    Returns:
        float: Duration of the operation in milliseconds.
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

        if existing_data:
            text = existing_data.decode("utf-8", errors="replace")
            sd_caption, parsed_meta = parse_sidecar_text(text, source=filename)
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

        final_sd_caption = sd_caption or published_caption
        content = build_caption_sidecar(final_sd_caption, meta)

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
        return duration

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
