from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.core.exceptions import AIServiceError, PublishingError, StorageError
from publisher_v2.core.models import CaptionSpec, PublishResult, WorkflowResult
from publisher_v2.services.ai import AIService
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.state import load_posted_hashes, save_posted_hash
from publisher_v2.utils.captions import (
    format_caption,
    build_metadata_phase1,
    build_metadata_phase2,
    build_caption_sidecar,
)
from publisher_v2.utils.logging import log_json, now_monotonic, elapsed_ms


class WorkflowOrchestrator:
    def __init__(
        self,
        config: ApplicationConfig,
        storage: DropboxStorage,
        ai_service: AIService,
        publishers: List[Publisher],
    ):
        self.config = config
        self.storage = storage
        self.ai_service = ai_service
        self.publishers = publishers
        self.logger = logging.getLogger("publisher_v2.workflow")

    async def execute(
        self, 
        select_filename: str | None = None, 
        dry_publish: bool = False,
        preview_mode: bool = False
    ) -> WorkflowResult:
        correlation_id = str(uuid.uuid4())
        selected_image = ""
        caption = ""
        tmp_path = ""
        selected_hash = ""
        temp_link = ""
        analysis = None
        spec = None
        dropbox_list_images_ms: int | None = None
        image_selection_ms: int | None = None
        vision_analysis_ms: int | None = None
        caption_generation_ms: int | None = None
        sidecar_write_ms: int | None = None
        publish_parallel_ms: int | None = None
        archive_ms: int | None = None

        def _log_timing() -> None:
            log_json(
                self.logger,
                logging.INFO,
                "workflow_timing",
                correlation_id=correlation_id,
                image=selected_image,
                dropbox_list_images_ms=dropbox_list_images_ms,
                image_selection_ms=image_selection_ms,
                vision_analysis_ms=vision_analysis_ms,
                caption_generation_ms=caption_generation_ms,
                sidecar_write_ms=sidecar_write_ms,
                publish_parallel_ms=publish_parallel_ms,
                archive_ms=archive_ms,
                preview_mode=preview_mode,
                dry_publish=dry_publish,
            )
        
        try:
            # 1. Select image (prefer unseen by sha256)
            list_start = now_monotonic()
            images = await self.storage.list_images(self.config.dropbox.image_folder)
            dropbox_list_images_ms = elapsed_ms(list_start)
            if not images:
                _log_timing()
                return WorkflowResult(
                    success=False,
                    image_name="",
                    caption="",
                    publish_results={},
                    archived=False,
                    error="No images found",
                    correlation_id=correlation_id,
                )
            import random

            selection_start = now_monotonic()
            posted_hashes = load_posted_hashes()
            random.shuffle(images)
            content = b""
            if select_filename:
                if select_filename not in images:
                    image_selection_ms = elapsed_ms(selection_start)
                    _log_timing()
                    return WorkflowResult(
                        success=False,
                        image_name="",
                        caption="",
                        publish_results={},
                        archived=False,
                        error=f"Selected file not found: {select_filename}",
                        correlation_id=correlation_id,
                    )
                selected_image = select_filename
                content = await self.storage.download_image(self.config.dropbox.image_folder, selected_image)
                selected_hash = hashlib.sha256(content).hexdigest()
            else:
                for name in images:
                    blob = await self.storage.download_image(self.config.dropbox.image_folder, name)
                    digest = hashlib.sha256(blob).hexdigest()
                    if digest in posted_hashes:
                        continue
                    selected_image = name
                    content = blob
                    selected_hash = digest
                    break

            if not selected_image:
                image_selection_ms = elapsed_ms(selection_start)
                _log_timing()
                return WorkflowResult(
                    success=False,
                    image_name="",
                    caption="",
                    publish_results={},
                    archived=False,
                    error="No new images to post (all duplicates)",
                    correlation_id=correlation_id,
                )

            # 2. Save to temp and get temporary link
            suffix = os.path.splitext(selected_image)[1]
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp.flush()
                tmp_path = tmp.name
            # Secure temp file permissions (0600)
            try:
                os.chmod(tmp_path, 0o600)
            except Exception:
                # Best-effort; continue if chmod not supported
                pass

            if image_selection_ms is None:
                image_selection_ms = elapsed_ms(selection_start)
            temp_link = await self.storage.get_temporary_link(self.config.dropbox.image_folder, selected_image)

            # 3. Analyze image with vision AI
            if not preview_mode:
                log_json(self.logger, logging.INFO, "vision_analysis_start", image=selected_image, correlation_id=correlation_id)
            analysis_start = now_monotonic()
            analysis = await self.ai_service.analyzer.analyze(temp_link)
            vision_analysis_ms = elapsed_ms(analysis_start)
            if not preview_mode:
                log_json(
                    self.logger,
                    logging.INFO,
                    "vision_analysis_complete",
                    image=selected_image,
                    description=analysis.description[:100],
                    mood=analysis.mood,
                    tags=analysis.tags[:5],
                    nsfw=analysis.nsfw,
                    safety_labels=analysis.safety_labels,
                    correlation_id=correlation_id,
                )

            # Optional: Filter NSFW content (future enhancement)
            # if analysis.nsfw and not self.config.content.allow_nsfw:
            #     return WorkflowResult(
            #         success=False, error="NSFW content blocked", ...
            #     )

            # 4. Generate caption from analysis
            # Build spec; for Email/FetLife we avoid hashtags and use shorter max length
            if self.config.platforms.email_enabled and self.config.email:
                spec = CaptionSpec(
                    platform="fetlife_email",
                    style="engagement_question",
                    hashtags="",
                    max_length=240,
                )
            else:
                spec = CaptionSpec(
                    platform="generic",
                    style="minimal_poetic",
                    hashtags=self.config.content.hashtag_string,
                    max_length=2200,
                )
            # Prefer SD single-call if enabled
            sd_caption = None
            if not preview_mode:
                log_json(self.logger, logging.INFO, "caption_generation_start", correlation_id=correlation_id)
            caption_start = now_monotonic()
            try:
                if self.config.openai.sd_caption_enabled and self.config.openai.sd_caption_single_call_enabled:
                    log_json(self.logger, logging.INFO, "sd_caption_start", correlation_id=correlation_id)
                    pair = await self.ai_service.generator.generate_with_sd(analysis, spec)
                    caption = pair.get("caption", "")
                    sd_caption = pair.get("sd_caption") or None
                    log_json(self.logger, logging.INFO, "sd_caption_complete", has_sd=bool(sd_caption), correlation_id=correlation_id)
                else:
                    caption = await self.ai_service.generator.generate(analysis, spec)
                if not preview_mode:
                    log_json(self.logger, logging.INFO, "caption_generated", caption_length=len(caption), correlation_id=correlation_id)
                caption_generation_ms = elapsed_ms(caption_start)
            except Exception as exc:
                if not preview_mode:
                    log_json(self.logger, logging.ERROR, "sd_caption_error", error=str(exc), correlation_id=correlation_id)
                # Fallback to legacy caption-only
                caption = await self.ai_service.generator.generate(analysis, spec)
                if not preview_mode:
                    log_json(self.logger, logging.INFO, "caption_generated", caption_length=len(caption), correlation_id=correlation_id)
                caption_generation_ms = elapsed_ms(caption_start)
            # In preview, attach sd_caption to analysis for display
            if analysis and sd_caption:
                setattr(analysis, "sd_caption", sd_caption)
            # Write sidecar if sd_caption present (no-op in preview/dry/debug)
            if sd_caption and not self.config.content.debug and not dry_publish and not preview_mode:
                sidecar_start = now_monotonic()
                try:
                    # Build metadata Phase 1
                    created_iso = (
                        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    )
                    model_version = getattr(self.ai_service.generator, "sd_caption_model", None) or getattr(self.ai_service.generator, "model", "")
                    db_meta = await self.storage.get_file_metadata(self.config.dropbox.image_folder, selected_image)
                    phase1 = build_metadata_phase1(
                        image_file=selected_image,
                        sha256=selected_hash,
                        created_iso=created_iso,
                        sd_caption_version="v1.0",
                        model_version=str(model_version),
                        dropbox_file_id=db_meta.get("id"),
                        dropbox_rev=db_meta.get("rev"),
                        artist_alias=self.config.captionfile.artist_alias,
                    )
                    # Optionally add Phase 2
                    meta = dict(phase1)
                    if self.config.captionfile.extended_metadata_enabled and analysis:
                        phase2 = build_metadata_phase2(analysis)
                        meta.update(phase2)
                    content = build_caption_sidecar(sd_caption, meta)
                    log_json(self.logger, logging.INFO, "sidecar_upload_start", image=selected_image, correlation_id=correlation_id)
                    await self.storage.write_sidecar_text(self.config.dropbox.image_folder, selected_image, content)
                    sidecar_write_ms = elapsed_ms(sidecar_start)
                    log_json(
                        self.logger,
                        logging.INFO,
                        "sidecar_upload_complete",
                        image=selected_image,
                        correlation_id=correlation_id,
                        sidecar_write_ms=sidecar_write_ms,
                    )
                except Exception as exc:
                    sidecar_write_ms = elapsed_ms(sidecar_start)
                    log_json(
                        self.logger,
                        logging.ERROR,
                        "sidecar_upload_error",
                        image=selected_image,
                        error=str(exc),
                        correlation_id=correlation_id,
                        sidecar_write_ms=sidecar_write_ms,
                    )

            # 5. Publish in parallel
            enabled_publishers = [p for p in self.publishers if p.is_enabled()]
            publish_results: Dict[str, PublishResult] = {}
            if enabled_publishers and not self.config.content.debug and not dry_publish and not preview_mode:
                publish_start = now_monotonic()
                results = await asyncio.gather(
                    *[
                        p.publish(
                            tmp_path,
                            format_caption(p.platform_name, caption),
                            context={"analysis_tags": analysis.tags} if analysis else None,
                        )
                        for p in enabled_publishers
                    ],
                    return_exceptions=True,
                )
                publish_parallel_ms = elapsed_ms(publish_start)
                for pub, res in zip(enabled_publishers, results):
                    if isinstance(res, Exception):
                        publish_results[pub.platform_name] = PublishResult(
                            success=False, platform=pub.platform_name, error=str(res)
                        )
                    else:
                        publish_results[pub.platform_name] = res
            else:
                # In debug mode, simulate success without publishing
                for p in enabled_publishers:
                    publish_results[p.platform_name] = PublishResult(success=True, platform=p.platform_name)
                if enabled_publishers:
                    publish_parallel_ms = 0

            any_success = any(r.success for r in publish_results.values()) if publish_results else self.config.content.debug

            # 6. Archive if any success and not debug
            archived = False
            if any_success and self.config.content.archive and not self.config.content.debug and not dry_publish and not preview_mode:
                archive_start = now_monotonic()
                await self.storage.archive_image(
                    self.config.dropbox.image_folder, selected_image, self.config.dropbox.archive_folder
                )
                archive_ms = elapsed_ms(archive_start)
                archived = True
                if selected_hash:
                    save_posted_hash(selected_hash)

            # Final summary timing log for the workflow
            image_selection_ms = image_selection_ms or 0
            _log_timing()

            return WorkflowResult(
                success=any_success,
                image_name=selected_image,
                caption=caption,
                publish_results=publish_results,
                archived=archived,
                correlation_id=correlation_id,
                # Preview mode fields
                image_analysis=analysis if preview_mode else None,
                caption_spec=spec if preview_mode else None,
                dropbox_url=temp_link if preview_mode else None,
                sha256=selected_hash if preview_mode else None,
                image_folder=self.config.dropbox.image_folder if preview_mode else None,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


