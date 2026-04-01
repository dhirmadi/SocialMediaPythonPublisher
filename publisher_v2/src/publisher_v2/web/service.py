import asyncio
import dataclasses
import json
import logging
import os
import random
import time
import urllib.parse
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

# Load .env early so CONFIG_PATH can come from it (for local development).
# This is idempotent and won't override existing env vars (e.g., on Heroku).
# Called at module import time to avoid test interference.
load_dotenv()

from publisher_v2.config.credentials import OpenAICredentials, SMTPCredentials, TelegramCredentials  # noqa: E402
from publisher_v2.config.loader import load_application_config  # noqa: E402
from publisher_v2.config.source import ConfigSource, RuntimeConfig  # noqa: E402
from publisher_v2.config.static_loader import get_static_config  # noqa: E402
from publisher_v2.core.exceptions import (  # noqa: E402
    CredentialResolutionError,
    OrchestratorUnavailableError,
    TenantNotFoundError,
)
from publisher_v2.core.workflow import WorkflowOrchestrator  # noqa: E402
from publisher_v2.services.ai import (  # noqa: E402
    AIService,
    CaptionGeneratorOpenAI,
    NullAIService,
    VisionAnalyzerOpenAI,
)
from publisher_v2.services.publishers import build_publishers  # noqa: E402
from publisher_v2.services.publishers.base import Publisher  # noqa: E402
from publisher_v2.services.storage import DropboxStorage  # noqa: E402
from publisher_v2.utils.logging import log_json  # noqa: E402
from publisher_v2.web.models import AnalysisResponse, CurationResponse, ImageResponse, PublishResponse  # noqa: E402
from publisher_v2.web.sidecar_parser import rehydrate_sidecar_view  # noqa: E402


class WebImageService:
    """
    Thin orchestration layer for the web interface.

    This service delegates to existing storage, AI, and workflow components
    and avoids duplicating business logic wherever possible.
    """

    def __init__(
        self,
        runtime: RuntimeConfig | None = None,
        config_source: ConfigSource | None = None,
    ) -> None:
        self.logger = logging.getLogger("publisher_v2.web")

        self._runtime = runtime
        self._config_source = config_source

        if runtime is None:
            # Standalone env-first initialization (existing behavior)
            config_path = os.environ.get("CONFIG_PATH")
            env_path = os.environ.get("ENV_PATH")

            # CONFIG_PATH is optional when all required env vars are set
            # (STORAGE_PATHS, PUBLISHERS, OPENAI_SETTINGS)
            cfg = load_application_config(config_path, env_path)
        else:
            cfg = runtime.config

        storage = DropboxStorage(cfg.dropbox)

        # AI may be resolved lazily in orchestrator mode (cfg.openai.api_key may be None)
        ai_service: AIService | None = None
        if getattr(cfg.openai, "api_key", None):
            analyzer = VisionAnalyzerOpenAI(cfg.openai)
            generator = CaptionGeneratorOpenAI(cfg.openai)
            ai_service = AIService(analyzer, generator)

        publishers: list[Publisher] = build_publishers(cfg)

        self.config = cfg
        self.storage = storage
        self.ai_service = ai_service
        self.publishers = publishers
        # Keep legacy behavior for standalone mode: orchestrator is ready immediately.
        # In orchestrator mode we build it lazily to allow late-binding publishers/AI.
        if runtime is None:
            if ai_service is None:
                # Should not happen in standalone mode because OPENAI_API_KEY is required by loader.
                analyzer = VisionAnalyzerOpenAI(cfg.openai)
                generator = CaptionGeneratorOpenAI(cfg.openai)
                ai_service = AIService(analyzer, generator)
                self.ai_service = ai_service
            self.orchestrator = WorkflowOrchestrator(cfg, storage, ai_service, publishers)
        else:
            self.orchestrator: WorkflowOrchestrator | None = None
        # Short-lived in-memory cache for Dropbox image listings to avoid
        # repeated list_images calls on hot paths (see CR 005-004).
        self._image_cache: list[str] | None = None
        self._image_cache_expiry: float | None = None
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
        self._recently_shown: list[str] = []

    def _is_orchestrated(self) -> bool:
        return self._runtime is not None and self._config_source is not None

    def _cred_ref(self, key: str) -> str | None:
        if not self._runtime or not self._runtime.credentials_refs:
            return None
        return self._runtime.credentials_refs.get(key)

    async def _ensure_ai_service(self) -> AIService | None:
        if self.ai_service is not None:
            return self.ai_service
        if not self._is_orchestrated():
            return None
        if not self.config.features.analyze_caption_enabled:
            return None

        ref = self._cred_ref("openai")
        if not ref:
            # No ref available -> disable feature
            self.config.features.analyze_caption_enabled = False
            return None

        try:
            data = await self._config_source.get_credentials(self._runtime.host, ref)  # type: ignore[union-attr]
            creds = OpenAICredentials.model_validate(data)
            new_openai = self.config.openai.model_copy(update={"api_key": creds.api_key})
            self.config = self.config.model_copy(update={"openai": new_openai})
            analyzer = VisionAnalyzerOpenAI(new_openai)
            generator = CaptionGeneratorOpenAI(new_openai)
            self.ai_service = AIService(analyzer, generator)
            return self.ai_service
        except (CredentialResolutionError, OrchestratorUnavailableError):
            log_json(self.logger, logging.WARNING, "ai_credential_resolution_failed", host=self._runtime.host)
            self.config.features.analyze_caption_enabled = False
            return None
        except (ValidationError, json.JSONDecodeError, TenantNotFoundError, TypeError) as exc:
            log_json(
                self.logger,
                logging.ERROR,
                "ai_credential_unexpected_error",
                host=self._runtime.host,
                error=str(exc),
            )
            self.config.features.analyze_caption_enabled = False
            return None

    async def _ensure_email_publisher(self) -> None:
        if not self._is_orchestrated():
            return
        if not self.config.platforms.email_enabled or not self.config.email:
            return
        if getattr(self.config.email, "password", None):
            return
        ref = self._cred_ref("smtp")
        if not ref:
            self.config.platforms.email_enabled = False
            return
        try:
            data = await self._config_source.get_credentials(self._runtime.host, ref)  # type: ignore[union-attr]
            creds = SMTPCredentials.model_validate(data)
            new_email = self.config.email.model_copy(update={"password": creds.password})
            self.config = self.config.model_copy(update={"email": new_email})
        except (CredentialResolutionError, OrchestratorUnavailableError):
            log_json(self.logger, logging.WARNING, "email_credential_resolution_failed", host=self._runtime.host)
            self.config.platforms.email_enabled = False
        except (ValidationError, json.JSONDecodeError, TenantNotFoundError, TypeError) as exc:
            log_json(
                self.logger,
                logging.ERROR,
                "email_credential_unexpected_error",
                host=self._runtime.host,
                error=str(exc),
            )
            self.config.platforms.email_enabled = False

    async def _ensure_telegram_publisher(self) -> None:
        if not self._is_orchestrated():
            return
        if not self.config.platforms.telegram_enabled or not self.config.telegram:
            return
        if getattr(self.config.telegram, "bot_token", None):
            return
        ref = self._cred_ref("telegram")
        if not ref:
            self.config.platforms.telegram_enabled = False
            return
        try:
            data = await self._config_source.get_credentials(self._runtime.host, ref)  # type: ignore[union-attr]
            creds = TelegramCredentials.model_validate(data)
            new_tg = self.config.telegram.model_copy(update={"bot_token": creds.bot_token})
            self.config = self.config.model_copy(update={"telegram": new_tg})
        except (CredentialResolutionError, OrchestratorUnavailableError):
            log_json(self.logger, logging.WARNING, "telegram_credential_resolution_failed", host=self._runtime.host)
            self.config.platforms.telegram_enabled = False
        except (ValidationError, json.JSONDecodeError, TenantNotFoundError, TypeError) as exc:
            log_json(
                self.logger,
                logging.ERROR,
                "telegram_credential_unexpected_error",
                host=self._runtime.host,
                error=str(exc),
            )
            self.config.platforms.telegram_enabled = False

    async def _ensure_publishers(self) -> None:
        """
        In orchestrator mode, resolve optional publisher secrets lazily before publishing.
        """
        await self._ensure_email_publisher()
        await self._ensure_telegram_publisher()

        self.publishers = build_publishers(self.config)

    async def _ensure_orchestrator(self) -> WorkflowOrchestrator:
        if self.orchestrator is not None:
            self.orchestrator.publishers = self.publishers
            return self.orchestrator

        ai = await self._ensure_ai_service()
        ai_service = ai if ai is not None else NullAIService()
        self.orchestrator = WorkflowOrchestrator(self.config, self.storage, ai_service, self.publishers)  # type: ignore[arg-type]
        return self.orchestrator

    async def _get_cached_images(self) -> list[str]:
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
        sidecar_result = await self.storage.download_sidecar_if_exists(self.config.dropbox.image_folder, filename)

        caption = None
        sd_caption = None
        metadata: dict[str, Any] | None = None
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

        # Exclude recently-shown images for shuffle-without-replacement behavior
        candidates = [img for img in images if img not in self._recently_shown]
        if not candidates:
            # Full cycle complete — reset and use all images
            self._recently_shown.clear()
            candidates = list(images)

        selected = random.choice(candidates)
        self._recently_shown.append(selected)

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

    async def list_images(self) -> dict[str, Any]:
        """
        Return a sorted list of all valid image filenames.
        Uses in-memory caching to avoid hitting Dropbox too frequently.
        """
        images = await self._get_cached_images()
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
        self, filename: str, correlation_id: str | None = None, force_refresh: bool = False
    ) -> AnalysisResponse:
        # Ensure file exists by trying to get a temp link
        temp_link = await self.storage.get_temporary_link(self.config.dropbox.image_folder, filename)

        # Sidecar-first cache path when not forcing refresh.
        if not force_refresh:
            blob = await self.storage.download_sidecar_if_exists(self.config.dropbox.image_folder, filename)
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

        # Ensure AI is available (or degrade to disabled).
        ai = await self._ensure_ai_service()
        if ai is None:
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
        analysis = await ai.analyzer.analyze(temp_link)

        from publisher_v2.core.models import CaptionSpec

        spec = CaptionSpec.for_config(self.config)

        # Generate caption + sd_caption via centralized AIService helper.
        sd_caption = None
        try:
            caption, sd_caption = await ai.create_caption_pair_from_analysis(analysis, spec)
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
            caption = await ai.create_caption(temp_link, spec)

        # Attach sd_caption for downstream sidecar metadata builder
        if sd_caption:
            analysis = dataclasses.replace(analysis, sd_caption=sd_caption)

        # Write sidecar (mimic workflow sidecar behaviour)
        sidecar_written = False
        if sd_caption and not self.config.content.debug:
            from publisher_v2.services.sidecar import generate_and_upload_sidecar

            model_version = getattr(ai.generator, "sd_caption_model", None) or getattr(ai.generator, "model", "")
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
                    log_prefix="web_sidecar_upload",
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

    async def publish_image(
        self,
        filename: str,
        platforms: list[str] | None = None,
        caption_override: str | None = None,
    ) -> PublishResponse:
        """
        Publish a specific image by delegating to the existing WorkflowOrchestrator.

        Platforms list is currently advisory only; for MVP we respect the
        enabled flags from config and still reuse the orchestrator behaviour.

        When caption_override is provided, the orchestrator skips AI caption
        generation and uses the caller-supplied text instead.
        """
        if not self.config.features.publish_enabled:
            log_json(
                self.logger,
                logging.INFO,
                "web_feature_publish_disabled",
                image=filename,
            )
            raise PermissionError("Publish feature is disabled via FEATURE_PUBLISH toggle")

        if caption_override:
            log_json(
                self.logger,
                logging.INFO,
                "web_publish_caption_override",
                image=filename,
                override_length=len(caption_override),
            )

        # Resolve optional publisher secrets lazily (telegram/smtp) before publishing.
        await self._ensure_publishers()

        orchestrator = await self._ensure_orchestrator()
        result = await orchestrator.execute(
            select_filename=filename,
            dry_publish=False,
            preview_mode=False,
            caption_override=caption_override,
        )
        # Convert results to simple dict form
        results: dict[str, dict[str, Any]] = {}
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

        orchestrator = await self._ensure_orchestrator()
        await orchestrator.keep_image(
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

        orchestrator = await self._ensure_orchestrator()
        await orchestrator.remove_image(
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

    async def delete_image(self, filename: str) -> CurationResponse:
        """
        Permanently delete the specified image from storage.

        This is a destructive operation and cannot be undone.
        """
        if not self.config.features.delete_enabled:
            log_json(
                self.logger,
                logging.INFO,
                "web_feature_delete_disabled",
                image=filename,
            )
            raise PermissionError("Delete feature is disabled via FEATURE_DELETE toggle")

        orchestrator = await self._ensure_orchestrator()
        await orchestrator.delete_image(
            filename,
            preview_mode=False,
            dry_run=False,
        )

        return CurationResponse(
            filename=filename,
            action="delete",
            destination_folder="",  # No destination - permanently deleted
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
