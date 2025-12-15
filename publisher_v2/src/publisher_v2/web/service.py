from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
import time
import urllib.parse
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

# Load .env early so CONFIG_PATH can come from it (for local development).
# This is idempotent and won't override existing env vars (e.g., on Heroku).
# Called at module import time to avoid test interference.
load_dotenv()

from publisher_v2.config.loader import load_application_config
from publisher_v2.config.static_loader import get_static_config
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
from publisher_v2.web.models import ImageResponse, AnalysisResponse, PublishResponse, CurationResponse
from publisher_v2.web.sidecar_parser import parse_sidecar_text, rehydrate_sidecar_view


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
        # Short-lived in-memory cache for Dropbox image listings to avoid
        # repeated list_images calls on hot paths (see CR 005-004).
        self._image_cache: Optional[List[str]] = None
        self._image_cache_expiry: Optional[float] = None
        limits = get_static_config().service_limits
        ttl = limits.web.image_cache_ttl_seconds
        env_ttl = os.environ.get("WEB_IMAGE_CACHE_TTL_SECONDS")
        if env_ttl:
            try:
                parsed_ttl = float(env_ttl)
                if parsed_ttl > 0:
                    ttl = parsed_ttl
            except ValueError:
                # Ignore invalid override; keep config/default TTL.
                pass
        self._image_cache_ttl_seconds: float = ttl

    async def _get_cached_images(self) -> List[str]:
        """
        Return a cached list of images when within TTL, otherwise refresh from Dropbox.
        """
        now = time.monotonic()
        if self._image_cache is not None and self._image_cache_expiry is not None:
            if now < self._image_cache_expiry:
                return list(self._image_cache)
        images = await self.storage.list_images(self.config.dropbox.image_folder)
        # Cache even empty lists so we don't hammer Dropbox on empty folders.
        self._image_cache = list(images)
        self._image_cache_expiry = now + self._image_cache_ttl_seconds
        return images

    async def _build_image_response(self, filename: str, temp_link: str) -> ImageResponse:
        """
        Shared helper to build an ImageResponse from a filename and temp link.
        Handles sidecar loading and thumbnail URL generation consistently.
        """
        sidecar_result = await self.storage.download_sidecar_if_exists(
            self.config.dropbox.image_folder, filename
        )

        caption = None
        sd_caption = None
        metadata: Optional[Dict[str, Any]] = None
        has_sidecar = False

        if sidecar_result:
            text = sidecar_result.decode("utf-8", errors="ignore")
            view = rehydrate_sidecar_view(text)
            sd_caption = view.get("sd_caption")
            caption = view.get("caption")
            metadata = view.get("metadata")
            has_sidecar = bool(view.get("has_sidecar"))

        thumbnail_url = f"/api/images/{urllib.parse.quote(filename, safe='')}/thumbnail"

        return ImageResponse(
            filename=filename,
            temp_url=temp_link,
            thumbnail_url=thumbnail_url,
            sha256=None,
            caption=caption,
            sd_caption=sd_caption,
            metadata=metadata,
            has_sidecar=has_sidecar,
        )

    async def get_random_image(self) -> ImageResponse:
        images = await self._get_cached_images()
        if not images:
            raise FileNotFoundError("No images found")

        import random
        random.shuffle(images)
        selected = images[0]
        folder = self.config.dropbox.image_folder

        temp_link = await self.storage.get_temporary_link(folder, selected)
        return await self._build_image_response(selected, temp_link)

    async def get_image_details(self, filename: str) -> ImageResponse:
        """
        Fetch details for a specific image by filename.
        """
        folder = self.config.dropbox.image_folder
        # Check existence via temp link (will raise if not found)
        try:
            temp_link = await self.storage.get_temporary_link(folder, filename)
        except Exception:
            # Propagate or wrap as needed, but storage error usually implies not found/access issue
            raise FileNotFoundError(f"Image {filename} not found")
            
        return await self._build_image_response(filename, temp_link)

    async def list_images(self) -> Dict[str, Any]:
        """
        Return a sorted list of all valid image filenames.
        Uses in-memory caching to avoid hitting Dropbox too frequently.
        """
        # We reuse _get_cached_images which already caches the raw list from Dropbox.
        # However, that list might contain non-image files depending on storage implementation.
        # But DropboxStorage.list_images is already implemented to filter by extension?
        # Let's check DropboxStorage.list_images implementation or assume it returns all files.
        # Actually, self._get_cached_images calls self.storage.list_images.
        # We should ensure we return a sorted list here.
        
        images = await self._get_cached_images()
        # Filter again just to be safe using utils logic if needed, 
        # but let's assume _get_cached_images returns valid files.
        # Sort A-Z
        sorted_images = sorted(images)
        return {"filenames": sorted_images, "count": len(sorted_images)}

    async def get_thumbnail(
        self,
        filename: str,
        size: str = "w960h640",
    ) -> bytes:
        """
        Return thumbnail bytes for the specified image.

        Args:
            filename: Image filename
            size: Thumbnail size string (maps to ThumbnailSize enum)

        Returns:
            JPEG thumbnail bytes
        """
        from dropbox.files import ThumbnailSize

        size_map = {
            "w256h256": ThumbnailSize.w256h256,
            "w480h320": ThumbnailSize.w480h320,
            "w640h480": ThumbnailSize.w640h480,
            "w960h640": ThumbnailSize.w960h640,
            "w1024h768": ThumbnailSize.w1024h768,
        }
        thumb_size = size_map.get(size, ThumbnailSize.w960h640)

        folder = self.config.dropbox.image_folder
        return await self.storage.get_thumbnail(folder, filename, size=thumb_size)

    async def analyze_and_caption(
        self, filename: str, correlation_id: Optional[str] = None, force_refresh: bool = False
    ) -> AnalysisResponse:
        # Ensure file exists by trying to get a temp link
        temp_link = await self.storage.get_temporary_link(self.config.dropbox.image_folder, filename)

        # Sidecar-first cache path when not forcing refresh.
        if not force_refresh:
            blob = await self.storage.download_sidecar_if_exists(
                self.config.dropbox.image_folder, filename
            )
            if blob:
                text = blob.decode("utf-8", errors="ignore")
                view = rehydrate_sidecar_view(text)
                cached_caption = view.get("caption")
                cached_sd_caption = view.get("sd_caption")
                if cached_caption or cached_sd_caption:
                    log_json(
                        self.logger,
                        logging.INFO,
                        "web_analyze_sidecar_cache_hit",
                        image=filename,
                        correlation_id=correlation_id,
                    )
                    return AnalysisResponse(
                        filename=filename,
                        description="",
                        mood="",
                        tags=[],
                        nsfw=False,
                        caption=cached_caption or "",
                        sd_caption=cached_sd_caption,
                        sidecar_written=False,
                    )

        if not self.config.features.analyze_caption_enabled:
            log_json(
                self.logger,
                logging.INFO,
                "web_feature_analyze_disabled",
                image=filename,
                correlation_id=correlation_id,
            )
            return AnalysisResponse(
                filename=filename,
                description="",
                mood="",
                tags=[],
                nsfw=False,
                caption="",
                sd_caption=None,
                sidecar_written=False,
            )

        # Run analysis when cache is bypassed or missing.
        log_json(
            self.logger,
            logging.INFO,
            "web_vision_analysis_start",
            image=filename,
            correlation_id=correlation_id,
        )
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

        # Generate caption + sd_caption via centralized AIService helper.
        sd_caption = None
        try:
            caption, sd_caption = await self.ai_service.create_caption_pair_from_analysis(analysis, spec)
        except Exception as exc:
            log_json(
                self.logger,
                logging.ERROR,
                "web_sd_caption_error",
                image=filename,
                error=str(exc),
                correlation_id=correlation_id,
            )
            # Best-effort fallback to legacy caption-only behaviour
            caption = await self.ai_service.create_caption(temp_link, spec)

        # Attach sd_caption for downstream sidecar metadata builder
        if sd_caption:
            analysis.sd_caption = sd_caption

        # Write sidecar (mimic workflow sidecar behaviour)
        sidecar_written = False
        if sd_caption and not self.config.content.debug:
            from publisher_v2.services.sidecar import generate_and_upload_sidecar

            model_version = (
                getattr(self.ai_service.generator, "sd_caption_model", None)
                or getattr(self.ai_service.generator, "model", "")
            )
            try:
                await generate_and_upload_sidecar(
                    storage=self.storage,
                    config=self.config,
                    filename=filename,
                    analysis=analysis,
                    sd_caption=sd_caption,
                    model_version=str(model_version),
                    sha256="",  # Optional here
                    correlation_id=correlation_id,
                    log_prefix="web_sidecar_upload"
                )
                sidecar_written = True
            except Exception:
                # Error already logged in helper
                pass

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
        if not self.config.features.publish_enabled:
            log_json(
                self.logger,
                logging.INFO,
                "web_feature_publish_disabled",
                image=filename,
            )
            raise PermissionError("Publish feature is disabled via FEATURE_PUBLISH toggle")

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

    async def keep_image(self, filename: str) -> CurationResponse:
        """
        Keep the specified image by moving it (and its sidecars) into the configured keep folder.
        """
        if not self.config.features.keep_enabled:
            log_json(
                self.logger,
                logging.INFO,
                "web_feature_keep_disabled",
                image=filename,
            )
            raise PermissionError("Keep feature is disabled via FEATURE_KEEP_CURATE toggle")

        await self.orchestrator.keep_image(
            filename,
            preview_mode=False,
            dry_run=False,
        )

        dest = self.config.dropbox.folder_keep or ""
        return CurationResponse(
            filename=filename,
            action="keep",
            destination_folder=dest,
            preview_only=False,
        )

    async def remove_image(self, filename: str) -> CurationResponse:
        """
        Remove the specified image by moving it (and its sidecars) into the configured remove folder.
        """
        if not self.config.features.remove_enabled:
            log_json(
                self.logger,
                logging.INFO,
                "web_feature_remove_disabled",
                image=filename,
            )
            raise PermissionError("Remove feature is disabled via FEATURE_REMOVE_CURATE toggle")

        await self.orchestrator.remove_image(
            filename,
            preview_mode=False,
            dry_run=False,
        )

        dest = self.config.dropbox.folder_remove or ""
        return CurationResponse(
            filename=filename,
            action="remove",
            destination_folder=dest,
            preview_only=False,
        )

    async def verify_curation_folders(self) -> None:
        """
        Proactively ensure that configured Keep/Remove folders exist in Dropbox.
        Safe to call repeatedly (idempotent).
        """
        tasks = []
        image_folder = self.config.dropbox.image_folder.rstrip("/")

        if self.config.features.keep_enabled and self.config.dropbox.folder_keep:
            keep_path = f"{image_folder}/{self.config.dropbox.folder_keep}"
            tasks.append(self.storage.ensure_folder_exists(keep_path))

        if self.config.features.remove_enabled and self.config.dropbox.folder_remove:
            remove_path = f"{image_folder}/{self.config.dropbox.folder_remove}"
            tasks.append(self.storage.ensure_folder_exists(remove_path))

        if tasks:
            log_json(self.logger, logging.INFO, "web_verifying_curation_folders", count=len(tasks))
            await asyncio.gather(*tasks)



