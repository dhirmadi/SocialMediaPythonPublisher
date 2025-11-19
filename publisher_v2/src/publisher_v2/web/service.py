from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from typing import List, Dict, Any, Optional

from publisher_v2.config.loader import load_application_config
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.publishers.email import EmailPublisher
from publisher_v2.services.publishers.telegram import TelegramPublisher
from publisher_v2.services.publishers.instagram import InstagramPublisher
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.utils.logging import log_json
from publisher_v2.utils.captions import (
    build_metadata_phase1,
    build_metadata_phase2,
    build_caption_sidecar,
)
from publisher_v2.web.models import ImageResponse, AnalysisResponse, PublishResponse
from publisher_v2.web.sidecar_parser import parse_sidecar_text


class WebImageService:
    """
    Thin orchestration layer for the web interface.

    This service delegates to existing storage, AI, and workflow components
    and avoids duplicating business logic wherever possible.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger("publisher_v2.web")

        config_path = os.environ.get("CONFIG_PATH")
        if not config_path:
            raise RuntimeError("CONFIG_PATH environment variable must be set for web interface")
        env_path = os.environ.get("ENV_PATH")

        cfg = load_application_config(config_path, env_path)

        storage = DropboxStorage(cfg.dropbox)
        analyzer = VisionAnalyzerOpenAI(cfg.openai)
        generator = CaptionGeneratorOpenAI(cfg.openai)
        ai_service = AIService(analyzer, generator)

        publishers: List[Publisher] = [
            TelegramPublisher(cfg.telegram, cfg.platforms.telegram_enabled),
            EmailPublisher(cfg.email, cfg.platforms.email_enabled),
            InstagramPublisher(cfg.instagram, cfg.platforms.instagram_enabled),
        ]

        self.config = cfg
        self.storage = storage
        self.ai_service = ai_service
        self.publishers = publishers
        self.orchestrator = WorkflowOrchestrator(cfg, storage, ai_service, publishers)

    async def get_random_image(self) -> ImageResponse:
        images = await self.storage.list_images(self.config.dropbox.image_folder)
        if not images:
            # FastAPI layer will translate into 404
            raise FileNotFoundError("No images found")

        import random

        random.shuffle(images)
        selected = images[0]

        # Get temporary link
        temp_link = await self.storage.get_temporary_link(self.config.dropbox.image_folder, selected)

        # Attempt to read sidecar
        caption = None
        sd_caption = None
        metadata: Optional[Dict[str, Any]] = None
        has_sidecar = False

        sidecar_name = os.path.splitext(selected)[0] + ".txt"
        try:
            # Reuse Dropbox storage to download sidecar if present
            # This uses the same download API as images
            blob = await self.storage.download_image(self.config.dropbox.image_folder, sidecar_name)
        except Exception:
            blob = b""

        if blob:
            has_sidecar = True
            text = blob.decode("utf-8", errors="ignore")
            sd_caption, metadata = parse_sidecar_text(text)
            # For UI convenience, treat sd_caption as caption fallback if no other caption is stored
            caption = metadata.get("caption") if isinstance(metadata, dict) else None
            if not caption:
                caption = sd_caption

        # Optionally compute hash for display (not used for dedup here)
        sha256 = None
        try:
            image_bytes = await self.storage.download_image(self.config.dropbox.image_folder, selected)
            sha256 = hashlib.sha256(image_bytes).hexdigest()
        except Exception:
            sha256 = None

        return ImageResponse(
            filename=selected,
            temp_url=temp_link,
            sha256=sha256,
            caption=caption,
            sd_caption=sd_caption,
            metadata=metadata,
            has_sidecar=has_sidecar,
        )

    async def analyze_and_caption(self, filename: str) -> AnalysisResponse:
        # Ensure file exists by trying to get a temp link
        temp_link = await self.storage.get_temporary_link(self.config.dropbox.image_folder, filename)

        # Run analysis
        log_json(self.logger, logging.INFO, "web_vision_analysis_start", image=filename)
        analysis = await self.ai_service.analyzer.analyze(temp_link)

        # Build spec consistent with orchestrator behaviour
        from publisher_v2.core.models import CaptionSpec

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

        # Generate caption + sd_caption using single-call if enabled
        sd_caption = None
        try:
            if self.config.openai.sd_caption_enabled and self.config.openai.sd_caption_single_call_enabled:
                pair = await self.ai_service.generator.generate_with_sd(analysis, spec)
                caption = pair.get("caption", "")
                sd_caption = pair.get("sd_caption") or None
            else:
                caption = await self.ai_service.generator.generate(analysis, spec)
        except Exception as exc:
            log_json(self.logger, logging.ERROR, "web_sd_caption_error", image=filename, error=str(exc))
            caption = await self.ai_service.generator.generate(analysis, spec)

        # Attach sd_caption for downstream sidecar metadata builder
        if sd_caption:
            analysis.sd_caption = sd_caption

        # Write sidecar (mimic workflow sidecar behaviour)
        sidecar_written = False
        if sd_caption and not self.config.content.debug:
            try:
                from datetime import datetime, timezone

                created_iso = (
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                )
                model_version = (
                    getattr(self.ai_service.generator, "sd_caption_model", None)
                    or getattr(self.ai_service.generator, "model", "")
                )
                db_meta = await self.storage.get_file_metadata(self.config.dropbox.image_folder, filename)
                phase1 = build_metadata_phase1(
                    image_file=filename,
                    sha256="",  # Optional here; workflow path already captures posted hashes
                    created_iso=created_iso,
                    sd_caption_version="v1.0",
                    model_version=str(model_version),
                    dropbox_file_id=db_meta.get("id"),
                    dropbox_rev=db_meta.get("rev"),
                    artist_alias=self.config.captionfile.artist_alias,
                )
                meta = dict(phase1)
                if self.config.captionfile.extended_metadata_enabled:
                    meta.update(build_metadata_phase2(analysis))
                content = build_caption_sidecar(sd_caption, meta)
                log_json(self.logger, logging.INFO, "web_sidecar_upload_start", image=filename)
                await self.storage.write_sidecar_text(self.config.dropbox.image_folder, filename, content)
                sidecar_written = True
                log_json(self.logger, logging.INFO, "web_sidecar_upload_complete", image=filename)
            except Exception as exc:
                log_json(self.logger, logging.ERROR, "web_sidecar_upload_error", image=filename, error=str(exc))

        return AnalysisResponse(
            filename=filename,
            description=analysis.description,
            mood=analysis.mood,
            tags=analysis.tags,
            nsfw=analysis.nsfw,
            caption=caption,
            sd_caption=sd_caption,
            sidecar_written=sidecar_written,
        )

    async def publish_image(self, filename: str, platforms: Optional[List[str]] = None) -> PublishResponse:
        """
        Publish a specific image by delegating to the existing WorkflowOrchestrator.

        Platforms list is currently advisory only; for MVP we respect the
        enabled flags from config and still reuse the orchestrator behaviour.
        """
        # The orchestrator will:
        #   - re-select the filename
        #   - re-run analysis/caption if needed
        #   - publish and archive on success
        # We call it with dry_publish=False and preview_mode=False.

        result = await self.orchestrator.execute(
            select_filename=filename,
            dry_publish=False,
            preview_mode=False,
        )
        # Convert results to simple dict form
        results: Dict[str, Dict[str, Any]] = {}
        for name, pr in result.publish_results.items():
            results[name] = {
                "success": pr.success,
                "post_id": pr.post_id,
                "error": pr.error,
            }

        any_success = result.success
        archived = result.archived

        return PublishResponse(
            filename=filename,
            results=results,
            archived=archived,
            any_success=any_success,
        )



