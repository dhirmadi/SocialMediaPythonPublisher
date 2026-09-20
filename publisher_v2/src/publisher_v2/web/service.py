import asyncio
import dataclasses
import json
import logging
import os
import random
import time
import urllib.parse
from collections import OrderedDict, deque
from typing import Any
from weakref import WeakKeyDictionary

from dotenv import load_dotenv
from pydantic import ValidationError

# Load .env early so CONFIG_PATH can come from it (for local development).
# This is idempotent and won't override existing env vars (e.g., on Heroku).
# Called at module import time to avoid test interference.
load_dotenv()

from publisher_v2.config.credentials import OpenAICredentials, SMTPCredentials, TelegramCredentials  # noqa: E402
from publisher_v2.config.loader import load_application_config  # noqa: E402
from publisher_v2.config.runtime_settings import load_runtime_settings  # noqa: E402
from publisher_v2.config.schema import ApplicationConfig  # noqa: E402
from publisher_v2.config.source import ConfigSource, RuntimeConfig  # noqa: E402
from publisher_v2.config.static_loader import get_static_config  # noqa: E402
from publisher_v2.core.exceptions import (  # noqa: E402
    AlreadyPublishedError,
    CredentialResolutionError,
    OrchestratorUnavailableError,
    PublishInProgressError,
    TenantNotFoundError,
)
from publisher_v2.core.workflow import ALREADY_PUBLISHED_ERROR, WorkflowOrchestrator  # noqa: E402
from publisher_v2.db import get_session_factory  # noqa: E402
from publisher_v2.db.caption_store import CaptionStore  # noqa: E402
from publisher_v2.db.publish_store import PublishStore  # noqa: E402
from publisher_v2.services.ai import (  # noqa: E402
    AIService,
    CaptionGeneratorOpenAI,
    NullAIService,
    VisionAnalyzerOpenAI,
    truncate_voice_profile_to_budget,
)
from publisher_v2.services.managed_storage import ManagedStorage  # noqa: E402
from publisher_v2.services.publishers import build_publishers  # noqa: E402
from publisher_v2.services.publishers.base import Publisher  # noqa: E402
from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view  # noqa: E402
from publisher_v2.services.storage_factory import create_storage  # noqa: E402
from publisher_v2.services.storage_ops_meter import StorageOpsMeter  # noqa: E402
from publisher_v2.services.storage_protocol import StorageProtocol, ThumbnailSize  # noqa: E402
from publisher_v2.services.usage_meter import UsageMeter  # noqa: E402
from publisher_v2.utils.logging import log_json  # noqa: E402
from publisher_v2.web.models import AnalysisResponse, CurationResponse, ImageResponse, PublishResponse  # noqa: E402


def _select_voice_examples(config: ApplicationConfig) -> list[str] | None:
    """Return voice examples to inject into caption prompts (PUB-029).

    None when voice matching is disabled or the profile is empty/unset; otherwise
    a token-budget-truncated list (deterministic: order preserved, drop from end).
    """
    if not getattr(config.features, "voice_matching_enabled", False):
        return None
    profile = getattr(config.content, "voice_profile", None)
    if not profile:
        return None
    return truncate_voice_profile_to_budget(profile)


# #139: without a publish store there is no DB lease, so serialize per-image
# publishes in-process — two concurrent clicks must not both get past the
# file-based "already posted" check. Kept process-wide rather than on the
# service: ``get_service`` is lru_cached, so a second instance needs only a
# first-call race, and a lock held on an instance that loses that race would
# protect nothing.
_PUBLISH_LOCKS: WeakKeyDictionary[asyncio.AbstractEventLoop, OrderedDict[tuple[str, str], asyncio.Lock]] = (
    WeakKeyDictionary()
)
# One lock per (tenant, image) ever published would grow for the life of the
# process, so old idle ones are dropped; a held lock is never evicted, since the
# next arrival would then build a fresh one and the serialization would be lost.
_PUBLISH_LOCK_MAX_KEYS = 1024


def _publish_lock(tenant: str, filename: str) -> asyncio.Lock:
    """Per-(tenant, image) publish lock, scoped to the running event loop."""
    loop = asyncio.get_running_loop()
    per_loop = _PUBLISH_LOCKS.get(loop)
    if per_loop is None:
        per_loop = OrderedDict()
        _PUBLISH_LOCKS[loop] = per_loop
    key = (tenant, filename)
    lock = per_loop.get(key)
    if lock is None:
        lock = asyncio.Lock()
    per_loop[key] = lock
    per_loop.move_to_end(key)
    for stale in [k for k in per_loop if len(per_loop) > _PUBLISH_LOCK_MAX_KEYS]:
        if stale == key or per_loop[stale].locked():
            continue
        del per_loop[stale]
    return lock


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
            # #86: deep-copy so nothing this service does can mutate the
            # runtime config object cached inside the orchestrator source.
            cfg = runtime.config.model_copy(deep=True)

        storage: StorageProtocol = create_storage(cfg)

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
        # Build usage meter for orchestrated mode
        self._usage_meter: UsageMeter | None = None
        if runtime is not None and config_source is not None:
            client = getattr(config_source, "orchestrator_client", None)
            if client is not None:
                self._usage_meter = UsageMeter(client=client, tenant_id=runtime.tenant)

        # PUB-045: Build storage ops meter when feature is enabled in orchestrator mode
        # with ManagedStorage. Standalone mode is unaffected (meter stays None).
        self._storage_ops_meter: StorageOpsMeter | None = None
        self._init_storage_ops_meter()

        # Caption history DB store (optional — graceful degradation if no DB)
        self._caption_store: CaptionStore | None = None
        self._publish_store: PublishStore | None = None
        sf = get_session_factory()
        if sf is not None:
            self._caption_store = CaptionStore(sf)
            self._publish_store = PublishStore(sf, lease_ttl_seconds=load_runtime_settings().publish_lease_ttl_seconds)

        self._tenant = runtime.tenant if runtime is not None else "default"

        # Keep legacy behavior for standalone mode: orchestrator is ready immediately.
        # In orchestrator mode we build it lazily to allow late-binding publishers/AI.
        if runtime is None:
            if ai_service is None:
                analyzer = VisionAnalyzerOpenAI(cfg.openai)
                generator = CaptionGeneratorOpenAI(cfg.openai)
                ai_service = AIService(analyzer, generator)
                self.ai_service = ai_service
            self.orchestrator: WorkflowOrchestrator | None = WorkflowOrchestrator(
                cfg,
                storage,
                ai_service,
                publishers,
                tenant=self._tenant,
                caption_store=self._caption_store,
                publish_store=self._publish_store,
            )
        else:
            self.orchestrator = None
        # Short-lived in-memory cache for Dropbox image listings to avoid
        # repeated list_images calls on hot paths (see CR 005-004).
        self._image_cache: list[str] | None = None
        self._image_cache_expiry: float | None = None
        limits = get_static_config().service_limits
        # #97 stage 2: env override parsed centrally; None -> static-config default.
        env_ttl = load_runtime_settings().web_image_cache_ttl_seconds
        self._image_cache_ttl_seconds: float = env_ttl if env_ttl is not None else limits.web.image_cache_ttl_seconds
        # #86: bounded — was an unbounded list.
        self._recently_shown: deque[str] = deque(maxlen=50)
        # #86: transient AI credential failures back off instead of flipping
        # feature flags; re-resolution is retried after the window expires.
        self._ai_unavailable_until: float | None = None

    def _init_storage_ops_meter(self) -> None:
        """PUB-045: build the storage ops meter when conditions are met.

        Meter is only constructed when orchestrator mode is active, an
        orchestrator client is available, ``ManagedStorage`` is the storage
        backend, and the feature flag is enabled.

        The flag comes from the app config only (#97 stage 1): loader.py in
        standalone mode, runtime config in orchestrator mode. The previous
        ``FEATURE_STORAGE_OPS_METERING`` env re-read is gone.
        """
        self._storage_ops_meter = None
        if self._runtime is None or self._config_source is None:
            return
        if not getattr(self.config.features, "storage_ops_metering_enabled", False):
            return
        if not isinstance(self.storage, ManagedStorage):
            return
        client = getattr(self._config_source, "orchestrator_client", None)
        if client is None:
            return
        self._storage_ops_meter = StorageOpsMeter(
            client=client,
            tenant_id=self._runtime.tenant,
            storage=self.storage,
        )
        self._storage_ops_meter.start_periodic_flush()
        log_json(
            self.logger,
            logging.INFO,
            "storage_ops_meter_initialized",
            tenant_id=self._runtime.tenant,
        )

    def _is_orchestrated(self) -> bool:
        return self._runtime is not None and self._config_source is not None

    async def aclose(self) -> None:
        """Release per-tenant resources on eviction/replacement (#86).

        Stops the storage-ops meter (final flush included), closes the OpenAI
        clients when the AI service provides ``aclose`` and the storage client
        when it does. Never raises.
        """
        meter = self._storage_ops_meter
        if meter is not None:
            try:
                await meter.stop_periodic_flush()
            except Exception:
                log_json(self.logger, logging.WARNING, "storage_ops_meter_close_failed", exc_info=True)
        usage_meter = self._usage_meter
        if usage_meter is not None:
            try:
                await usage_meter.aclose()
            except Exception:
                log_json(self.logger, logging.WARNING, "usage_meter_close_failed", exc_info=True)
        for target in (self.ai_service, self.storage):
            close = getattr(target, "aclose", None)
            if close is None:
                continue
            try:
                await close()
            except Exception:
                log_json(self.logger, logging.WARNING, "service_resource_close_failed", exc_info=True)

    def _cred_ref(self, key: str) -> str | None:
        if not self._runtime or not self._runtime.credentials_refs:
            return None
        return self._runtime.credentials_refs.get(key)

    _AI_BACKOFF_SECONDS = 60.0

    def _ai_backed_off(self) -> bool:
        until = self._ai_unavailable_until
        return until is not None and time.monotonic() < until

    def _start_ai_backoff(self) -> None:
        self._ai_unavailable_until = time.monotonic() + self._AI_BACKOFF_SECONDS

    async def _ensure_ai_service(self) -> AIService | None:
        """Resolve the AI service lazily in orchestrator mode.

        #86: failures NEVER mutate feature flags (the config used to be shared
        by reference with the orchestrator runtime cache, so one transient
        credential failure disabled AI for the tenant until eviction). Instead
        a 60s instance-level backoff suppresses retries, then resolution is
        attempted again.
        """
        if self.ai_service is not None:
            return self.ai_service
        if not self._is_orchestrated() or self._runtime is None or self._config_source is None:
            return None
        if not self.config.features.analyze_caption_enabled:
            return None
        if self._ai_backed_off():
            return None

        ref = self._cred_ref("openai")
        if not ref:
            # No ref available — treat as unavailable for now, retry later.
            self._start_ai_backoff()
            return None

        try:
            data = await self._config_source.get_credentials(self._runtime.host, ref, tenant=self._runtime.tenant)
            creds = OpenAICredentials.model_validate(data)
            new_openai = self.config.openai.model_copy(update={"api_key": creds.api_key})
            self.config = self.config.model_copy(update={"openai": new_openai})
            analyzer = VisionAnalyzerOpenAI(new_openai)
            generator = CaptionGeneratorOpenAI(new_openai)
            self.ai_service = AIService(analyzer, generator)
            self._ai_unavailable_until = None
            return self.ai_service
        except (CredentialResolutionError, OrchestratorUnavailableError):
            log_json(self.logger, logging.WARNING, "ai_credential_resolution_failed", host=self._runtime.host)
            self._start_ai_backoff()
            return None
        except (ValidationError, json.JSONDecodeError, TenantNotFoundError, TypeError) as exc:
            log_json(
                self.logger,
                logging.ERROR,
                "ai_credential_unexpected_error",
                host=self._runtime.host,
                error=str(exc),
            )
            self._start_ai_backoff()
            return None

    async def _ensure_email_publisher(self) -> None:
        if not self._is_orchestrated() or self._runtime is None or self._config_source is None:
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
            data = await self._config_source.get_credentials(self._runtime.host, ref, tenant=self._runtime.tenant)
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
        if not self._is_orchestrated() or self._runtime is None or self._config_source is None:
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
            data = await self._config_source.get_credentials(self._runtime.host, ref, tenant=self._runtime.tenant)
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
            # #86: never leave a cached NullAIService in place once the real
            # AI service becomes resolvable again.
            refreshed = await self._ensure_ai_service()
            if refreshed is not None:
                self.orchestrator.ai_service = refreshed
            return self.orchestrator

        ai = await self._ensure_ai_service()
        ai_service = ai if ai is not None else NullAIService()
        self.orchestrator = WorkflowOrchestrator(
            self.config,
            self.storage,
            ai_service,  # type: ignore[arg-type]
            self.publishers,
            usage_meter=self._usage_meter,
            storage_ops_meter=self._storage_ops_meter,
            tenant=self._tenant,
            caption_store=self._caption_store,
            publish_store=self._publish_store,
        )
        return self.orchestrator

    def invalidate_image_listing(self) -> None:
        """Drop the cached folder listing (#144).

        ensure_known_image reads this cache, so a library write must clear it or
        a file uploaded seconds ago cannot be moved until the TTL lapses — while
        the library panel, which lists storage directly, already shows it.
        """
        self._image_cache = None
        self._image_cache_expiry = None

    async def _get_cached_images(self) -> list[str]:
        """
        Return a cached list of images when within TTL, otherwise refresh from Dropbox.

        The single-flight lock prevents a thundering herd when many concurrent
        requests miss the cache simultaneously — only one runs ``list_images``
        and the rest wait for the same result.
        """
        now = time.monotonic()
        if self._image_cache is not None and self._image_cache_expiry is not None and now < self._image_cache_expiry:
            return list(self._image_cache)

        # Lazy-init the lock — async constructs prefer this so __init__ stays sync.
        lock = getattr(self, "_image_cache_lock", None)
        if lock is None:
            import asyncio as _asyncio

            lock = _asyncio.Lock()
            self._image_cache_lock = lock

        async with lock:
            now = time.monotonic()
            if (
                self._image_cache is not None
                and self._image_cache_expiry is not None
                and now < self._image_cache_expiry
            ):
                return list(self._image_cache)
            images = await self.storage.list_images(self.config.storage_paths.image_folder)
            self._image_cache = list(images)
            self._image_cache_expiry = now + self._image_cache_ttl_seconds
            return images

    async def _build_image_response(self, filename: str, temp_link: str) -> ImageResponse:
        """
        Shared helper to build an ImageResponse from a filename and temp link.
        Handles sidecar loading and thumbnail URL generation consistently.
        """
        sidecar_result = await self.storage.download_sidecar_if_exists(self.config.storage_paths.image_folder, filename)

        caption = None
        sd_caption = None
        metadata: dict[str, Any] | None = None
        has_sidecar = False

        if sidecar_result:
            text = sidecar_result.decode("utf-8", errors="ignore")
            view = rehydrate_sidecar_view(text, source=filename)
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

        folder = self.config.storage_paths.image_folder
        temp_link = await self.storage.get_temporary_link(folder, selected)
        return await self._build_image_response(selected, temp_link)

    _IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")

    async def ensure_known_image(self, filename: str) -> None:
        """#91 (SEC-11): only names from the image listing may reach storage.

        Blocks sidecar names (.txt), traversal-ish names and anything not in
        the current folder listing. Raises FileNotFoundError (mapped to 404).
        """
        if not filename or not filename.lower().endswith(self._IMAGE_SUFFIXES):
            raise FileNotFoundError(f"Image {filename} not found")
        images = await self._get_cached_images()
        if filename not in images:
            raise FileNotFoundError(f"Image {filename} not found")

    async def get_image_details(self, filename: str) -> ImageResponse:
        """
        Fetch details for a specific image by filename.
        """
        await self.ensure_known_image(filename)
        folder = self.config.storage_paths.image_folder
        # Check existence via temp link (will raise if not found)
        try:
            temp_link = await self.storage.get_temporary_link(folder, filename)
        except Exception:
            # Propagate or wrap as needed, but storage error usually implies not found/access issue
            raise FileNotFoundError(f"Image {filename} not found") from None

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
            size: Thumbnail size string (maps to protocol ThumbnailSize enum)

        Returns:
            JPEG thumbnail bytes
        """
        await self.ensure_known_image(filename)
        size_map = {
            "w256h256": ThumbnailSize.W256H256,
            "w480h320": ThumbnailSize.W480H320,
            "w640h480": ThumbnailSize.W640H480,
            "w960h640": ThumbnailSize.W960H640,
            "w1024h768": ThumbnailSize.W1024H768,
        }
        thumb_size = size_map.get(size, ThumbnailSize.W960H640)

        folder = self.config.storage_paths.image_folder
        return await self.storage.get_thumbnail(folder, filename, size=thumb_size)

    async def analyze_and_caption(
        self, filename: str, correlation_id: str | None = None, force_refresh: bool = False
    ) -> AnalysisResponse:
        await self.ensure_known_image(filename)
        try:
            return await self._analyze_and_caption_impl(filename, correlation_id, force_refresh)
        finally:
            # PUB-045: flush R2 storage ops counter regardless of outcome.
            meter = getattr(self, "_storage_ops_meter", None)
            if meter is not None:
                await meter.flush()

    def _select_cached_social_caption(self, view: dict[str, Any]) -> str | None:
        """Pick the social caption to serve from a sidecar cache view (#80).

        Preference: the published/edited `caption`, then the `caption_generated`
        entry for the first enabled platform, then the `email` entry, then any
        generated entry. Never the SD prompt.
        """
        cached = view.get("caption")
        if cached:
            return str(cached)
        generated = view.get("caption_generated")
        if not isinstance(generated, dict) or not generated:
            return None
        from publisher_v2.core.models import CaptionSpec

        for platform in CaptionSpec.for_platforms(self.config):
            value = generated.get(platform)
            if isinstance(value, str) and value.strip():
                return value
        email_value = generated.get("email")
        if isinstance(email_value, str) and email_value.strip():
            return email_value
        return next((str(v) for v in generated.values() if isinstance(v, str) and v.strip()), None)

    async def _analyze_and_caption_impl(
        self, filename: str, correlation_id: str | None = None, force_refresh: bool = False
    ) -> AnalysisResponse:
        # #140: since #93 vision reads bytes, so only the legacy
        # vision_max_dimension == 0 path still needs a link. Fetching one anyway
        # was a real API call on Dropbox and dead weight on R2 (where presigning
        # is local signing, not a billed op).
        # Existence is already enforced by the analyze_and_caption wrapper's
        # ensure_known_image(), which reads the cached listing — so on Dropbox an
        # image deleted since the last listing now fails in the download rather
        # than in the (dropped) temp-link call: same request, different
        # exception, until the TTL lapses.
        temp_link = ""
        if self.config.openai.vision_max_dimension <= 0:
            temp_link = await self.storage.get_temporary_link(self.config.storage_paths.image_folder, filename)

        # Sidecar-first cache path when not forcing refresh. #80: only a real
        # social caption (published/edited `caption` or a `caption_generated`
        # entry) may be served from cache — the SD prompt on line one is a
        # Stable Diffusion prompt, never a caption. Without a social caption,
        # fall through to the AI path.
        if not force_refresh:
            blob = await self.storage.download_sidecar_if_exists(self.config.storage_paths.image_folder, filename)
            if blob:
                text = blob.decode("utf-8", errors="ignore")
                view = rehydrate_sidecar_view(text, source=filename)
                cached_caption = self._select_cached_social_caption(view)
                if cached_caption:
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
                        caption=cached_caption,
                        sd_caption=view.get("sd_caption"),
                        sidecar_written=False,
                        cached=True,
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
        # #84: same hard AI-stage deadline as the workflow — a hung upstream
        # must fail the request, not hold the dyno past Heroku's H12 window.
        from publisher_v2.core.exceptions import AIServiceError
        from publisher_v2.core.workflow import _ai_stage_timeout_seconds

        ai_stage_deadline = time.monotonic() + _ai_stage_timeout_seconds()
        # #93 (PERF-2): pass bytes so vision never re-downloads the image; the
        # legacy presigned-URL path remains for vision_max_dimension == 0.
        analysis_source: str | bytes = temp_link
        if self.config.openai.vision_max_dimension > 0:
            analysis_source = await self.storage.download_image(self.config.storage_paths.image_folder, filename)
        try:
            analysis, vision_usage = await asyncio.wait_for(
                ai.analyzer.analyze(analysis_source),
                timeout=max(0.05, ai_stage_deadline - time.monotonic()),
            )
        except TimeoutError as exc:
            raise AIServiceError("ai stage timeout") from exc
        if self._usage_meter and vision_usage:
            await self._usage_meter.emit(vision_usage)

        from publisher_v2.core.models import CaptionSpec

        specs = CaptionSpec.for_platforms(self.config)
        spec = next(iter(specs.values()))  # primary spec for backward compat

        # Generate per-platform captions + sd_caption via centralized AIService helper.
        sd_caption = None
        platform_captions_dict: dict[str, str] | None = None
        # PUB-029: extract voice examples from config when voice matching is enabled.
        voice_examples = _select_voice_examples(self.config)

        # Fetch caption history for anti-repetition
        caption_history: dict[str, list[str]] | None = None
        if self._caption_store is not None:
            try:
                caption_history = await self._caption_store.fetch_recent_by_platform(
                    self._tenant, platforms=list(specs.keys())
                )
            except Exception:
                log_json(self.logger, logging.DEBUG, "web_caption_history_fetch_failed", correlation_id=correlation_id)

        try:
            caption_budget = max(0.05, ai_stage_deadline - time.monotonic())
            if hasattr(ai, "create_multi_caption_pair_from_analysis"):
                platform_captions_dict, sd_caption, caption_usages = await asyncio.wait_for(
                    ai.create_multi_caption_pair_from_analysis(
                        analysis, specs, history=caption_history, voice_examples=voice_examples
                    ),
                    timeout=caption_budget,
                )
                caption = next(iter((platform_captions_dict or {}).values()), "")
            else:
                caption, sd_caption, caption_usages = await asyncio.wait_for(
                    ai.create_caption_pair_from_analysis(analysis, spec), timeout=caption_budget
                )
            if self._usage_meter and caption_usages:
                await self._usage_meter.emit_all(caption_usages)
        except Exception as exc:
            log_json(
                self.logger,
                logging.ERROR,
                "web_sd_caption_error",
                image=filename,
                error=str(exc),
                correlation_id=correlation_id,
            )
            # Best-effort fallback to legacy caption-only behaviour, still
            # bounded by whatever remains of the AI-stage deadline (#84).
            try:
                caption, fallback_usages = await asyncio.wait_for(
                    ai.create_caption_from_analysis(analysis, spec),
                    timeout=max(0.05, ai_stage_deadline - time.monotonic()),
                )
            except TimeoutError as timeout_exc:
                raise AIServiceError("ai stage timeout") from timeout_exc
            if self._usage_meter and fallback_usages:
                await self._usage_meter.emit_all(fallback_usages)

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
                    platform_captions=platform_captions_dict,
                )
                sidecar_written = True
            except Exception:  # noqa: S110 — error already logged in helper
                pass

        return AnalysisResponse(
            filename=filename,
            description=analysis.description,
            mood=analysis.mood,
            tags=analysis.tags,
            nsfw=analysis.nsfw,
            caption=caption,
            sd_caption=sd_caption,
            alt_text=analysis.alt_text if self.config.features.alt_text_enabled else None,
            sidecar_written=sidecar_written,
            platform_captions=platform_captions_dict,
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
        await self.ensure_known_image(filename)
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
        lock = _publish_lock(self._tenant, filename)
        if lock.locked():
            # Fail fast instead of queueing behind a publish that can run for
            # minutes — the caller would otherwise hit a proxy timeout while the
            # first publish is still working.
            log_json(self.logger, logging.INFO, "web_publish_already_in_progress", image=filename)
            raise PublishInProgressError(f"A publish for {filename} is already in progress")
        async with lock:
            result = await orchestrator.execute(
                select_filename=filename,
                dry_publish=False,
                preview_mode=False,
                caption_override=caption_override,
            )
        if result.error and result.error.startswith(ALREADY_PUBLISHED_ERROR):
            # #139: no publish store, and this image is already in the posted set.
            log_json(self.logger, logging.INFO, "web_publish_already_published", image=filename)
            raise AlreadyPublishedError(result.error)
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
        await self.ensure_known_image(filename)
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

        dest = self.config.storage_paths.folder_keep or ""
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
        await self.ensure_known_image(filename)
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

        dest = self.config.storage_paths.folder_remove or ""
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
        await self.ensure_known_image(filename)
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
        image_folder = self.config.storage_paths.image_folder.rstrip("/")

        if self.config.features.keep_enabled and self.config.storage_paths.folder_keep:
            keep_path = f"{image_folder}/{self.config.storage_paths.folder_keep}"
            tasks.append(self.storage.ensure_folder_exists(keep_path))

        if self.config.features.remove_enabled and self.config.storage_paths.folder_remove:
            remove_path = f"{image_folder}/{self.config.storage_paths.folder_remove}"
            tasks.append(self.storage.ensure_folder_exists(remove_path))

        if tasks:
            log_json(self.logger, logging.INFO, "web_verifying_curation_folders", count=len(tasks))
            await asyncio.gather(*tasks)
