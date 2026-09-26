"""End-to-end publishing workflow: select, analyze, caption, publish, archive.

:class:`WorkflowOrchestrator` is the single place orchestration lives. It owns image
selection and dedup, the per-platform publish leases and their marks (#139), caption
sidecar writes, usage/storage metering, and the preview and dry-publish paths — both of
which must stay side-effect free: no publish, no archive, no state or cache mutation.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import logging
import os
import random
import tempfile
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from publisher_v2.db.caption_store import CaptionStore
    from publisher_v2.db.publish_store import PublishStore

from publisher_v2.config.runtime_settings import RuntimeSettings, load_runtime_settings
from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.exceptions import AIServiceError, PublishStoreUnavailableError, StorageError
from publisher_v2.core.models import CaptionSpec, ImageAnalysis, PublishResult, WorkflowResult
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage_protocol import StorageProtocol

if TYPE_CHECKING:
    from publisher_v2.services.storage_ops_meter import StorageOpsMeter
    from publisher_v2.services.usage_meter import UsageMeter

from publisher_v2.utils.captions import (
    format_caption,
)
from publisher_v2.utils.logging import elapsed_ms, log_json, now_monotonic
from publisher_v2.utils.state import (
    load_posted_content_hashes,
    load_posted_hashes,
    save_posted_content_hash,
    save_posted_hash,
)


@dataclasses.dataclass(slots=True)
class _ImageSelection:
    """Bundle returned by _select_image to keep execute() focused on workflow steps."""

    image_name: str
    content: bytes
    sha256: str
    content_hash: str
    dropbox_list_ms: int | None
    selection_ms: int | None
    error: str | None = None


# #139: prefix of the WorkflowResult.error a run returns when the file-based
# posted state (no publish store) refuses a re-publish. The web layer maps it to
# a 409 so the operator sees the reason instead of an empty result set.
ALREADY_PUBLISHED_ERROR = "Already published: "


class WorkflowOrchestrator:
    """Runs one publish attempt end to end for a single tenant."""

    def __init__(
        self,
        config: ApplicationConfig,
        storage: StorageProtocol,
        ai_service: AIService,
        publishers: list[Publisher],
        usage_meter: UsageMeter | None = None,
        storage_ops_meter: StorageOpsMeter | None = None,
        tenant: str = "default",
        caption_store: CaptionStore | None = None,
        publish_store: PublishStore | None = None,
        settings: RuntimeSettings | None = None,
    ):
        """Wire the collaborators one run needs.

        Args:
            config: Resolved application config for this tenant.
            storage: Storage backend holding the image library.
            ai_service: Vision analysis and caption generation.
            publishers: Platform publishers to fan out to; may be empty.
            usage_meter: Optional AI token/cost meter.
            storage_ops_meter: Optional storage-operation meter.
            tenant: Tenant label used in logs and store keys.
            caption_store: Optional caption history store.
            publish_store: Optional per-platform publish/lease store. When present it owns
                retry semantics, and the coarse file-based posted state no longer vetoes a
                run (#139).
            settings: Runtime tunables, read once here rather than per step (#143).
        """
        self.config = config
        self.storage = storage
        self.ai_service = ai_service
        self.publishers = publishers
        self._usage_meter = usage_meter
        self._storage_ops_meter = storage_ops_meter
        self._tenant = tenant
        self._caption_store = caption_store
        self._publish_store = publish_store
        # #139: platform -> the leased_at this run stamped, used to fence marks.
        self._lease_tokens: dict[str, datetime] = {}
        # #143: tunables are read once, when the orchestrator is built.
        self._settings = settings if settings is not None else load_runtime_settings()
        self.logger = logging.getLogger("publisher_v2.workflow")

    def _already_posted(
        self,
        sha256: str,
        content_hash: str,
        posted_hashes: set[str],
        posted_content_hashes: set[str],
    ) -> bool:
        """#139: file-state guard for an explicitly selected image.

        Only applies without a publish store. With a store, per-platform records
        own retry semantics (a partial publish must stay selectable), so the
        coarse file-based posted set must not veto the run.
        """
        if self._publish_store is not None:
            return False
        return bool((sha256 and sha256 in posted_hashes) or (content_hash and content_hash in posted_content_hashes))

    async def _select_image(
        self, select_filename: str | None = None, respect_posted_state: bool = True
    ) -> _ImageSelection:
        """Select the next image to publish, applying dedup logic.

        Uses Dropbox metadata-based dedup when a real Dropbox client is available,
        otherwise falls back to the legacy SHA256-only path (test/dummy storages).
        """
        image_folder = self.config.storage_paths.image_folder
        use_metadata = self.storage.supports_content_hashing()

        selected_image = ""
        content = b""
        selected_hash = ""
        selected_content_hash = ""
        dropbox_list_ms: int | None = None
        selection_ms: int | None = None

        if use_metadata:
            list_start = now_monotonic()
            images_with_hashes = await self.storage.list_images_with_hashes(image_folder)
            dropbox_list_ms = elapsed_ms(list_start)
            if not images_with_hashes:
                return _ImageSelection("", b"", "", "", dropbox_list_ms, None, error="No images found")

            selection_start = now_monotonic()
            posted_hashes = load_posted_hashes()
            posted_content_hashes = load_posted_content_hashes()

            random.shuffle(images_with_hashes)
            images = [name for name, _ in images_with_hashes]

            if select_filename:
                if select_filename not in images:
                    return _ImageSelection(
                        "",
                        b"",
                        "",
                        "",
                        dropbox_list_ms,
                        elapsed_ms(selection_start),
                        error=f"Selected file not found: {select_filename}",
                    )
                selected_image = select_filename
                for name, ch in images_with_hashes:
                    if name == select_filename:
                        selected_content_hash = ch or ""
                        break
                content = await self.storage.download_image(image_folder, selected_image)
                selected_hash = hashlib.sha256(content).hexdigest()
                if respect_posted_state and self._already_posted(
                    selected_hash, selected_content_hash, posted_hashes, posted_content_hashes
                ):
                    return _ImageSelection(
                        "",
                        b"",
                        "",
                        "",
                        dropbox_list_ms,
                        elapsed_ms(selection_start),
                        error=f"{ALREADY_PUBLISHED_ERROR}{select_filename}",
                    )
            else:
                # Fast-path: skip downloads when all content hashes are known and already posted
                if posted_content_hashes:
                    all_known = True
                    has_unposted = False
                    for _name, ch in images_with_hashes:
                        if not ch:
                            all_known = False
                            has_unposted = True
                            break
                        if ch not in posted_content_hashes:
                            has_unposted = True
                            break
                    if all_known and not has_unposted:
                        return _ImageSelection(
                            "",
                            b"",
                            "",
                            "",
                            dropbox_list_ms,
                            elapsed_ms(selection_start),
                            error="No new images to post (all duplicates)",
                        )

                # Prefer candidates whose content_hash is not already posted
                non_posted = [
                    (n, ch)
                    for n, ch in images_with_hashes
                    if ch and posted_content_hashes and ch not in posted_content_hashes
                ]
                remainder = [
                    (n, ch)
                    for n, ch in images_with_hashes
                    if not (ch and posted_content_hashes and ch not in posted_content_hashes)
                ]

                for name, ch in non_posted + remainder:
                    blob = await self.storage.download_image(image_folder, name)
                    digest = hashlib.sha256(blob).hexdigest()
                    if digest in posted_hashes:
                        continue
                    selected_image = name
                    content = blob
                    selected_hash = digest
                    selected_content_hash = ch or ""
                    break
        else:
            # Legacy path: list_images + SHA256-only dedup
            list_start = now_monotonic()
            images = await self.storage.list_images(image_folder)
            dropbox_list_ms = elapsed_ms(list_start)
            if not images:
                return _ImageSelection("", b"", "", "", dropbox_list_ms, None, error="No images found")

            selection_start = now_monotonic()
            posted_hashes = load_posted_hashes()
            random.shuffle(images)
            if select_filename:
                if select_filename not in images:
                    return _ImageSelection(
                        "",
                        b"",
                        "",
                        "",
                        dropbox_list_ms,
                        elapsed_ms(selection_start),
                        error=f"Selected file not found: {select_filename}",
                    )
                selected_image = select_filename
                content = await self.storage.download_image(image_folder, selected_image)
                selected_hash = hashlib.sha256(content).hexdigest()
                if respect_posted_state and self._already_posted(selected_hash, "", posted_hashes, set()):
                    return _ImageSelection(
                        "",
                        b"",
                        "",
                        "",
                        dropbox_list_ms,
                        elapsed_ms(selection_start),
                        error=f"{ALREADY_PUBLISHED_ERROR}{select_filename}",
                    )
            else:
                for name in images:
                    blob = await self.storage.download_image(image_folder, name)
                    digest = hashlib.sha256(blob).hexdigest()
                    if digest in posted_hashes:
                        continue
                    selected_image = name
                    content = blob
                    selected_hash = digest
                    break

        if not selected_image:
            return _ImageSelection(
                "",
                b"",
                "",
                "",
                dropbox_list_ms,
                elapsed_ms(selection_start),
                error="No new images to post (all duplicates)",
            )

        selection_ms = elapsed_ms(selection_start)
        return _ImageSelection(
            selected_image, content, selected_hash, selected_content_hash, dropbox_list_ms, selection_ms
        )

    async def execute(
        self,
        select_filename: str | None = None,
        dry_publish: bool = False,
        preview_mode: bool = False,
        caption_override: str | None = None,
        caption_overrides: dict[str, str] | None = None,
    ) -> WorkflowResult:
        """Run the full workflow once and return its outcome.

        On any exit path, leases this run took but never published are marked failed so the
        next run can re-lease them — unless the run held them past the lease TTL, in which
        case another run may already own them and the release is left to the TTL (#139).

        Args:
            select_filename: Publish this specific image instead of picking the next one.
            dry_publish: Run every step but skip the actual platform calls and state writes.
            preview_mode: Render what would happen; performs no publish, archive, sidecar
                write or state/cache mutation, and populates the preview-only fields of the
                result (analysis, spec, source URL, hash, folder).
            caption_override: Replace the generated caption for every platform.
            caption_overrides: Per-platform caption replacements; blank values are ignored.

        Returns:
            A WorkflowResult. Expected non-outcomes (nothing to publish, an image already
            published) come back as ``error`` text rather than an exception; an error
            prefixed with ``ALREADY_PUBLISHED_ERROR`` means file-based posted state refused
            the re-publish.

        Raises:
            AIServiceError: Vision or caption generation failed or timed out.
            StorageError: The image or its sidecar could not be read or written.
        """
        correlation_id = str(uuid.uuid4())
        caption = ""
        overrides: dict[str, str] = {}
        tmp_path = ""
        variant_paths: dict[str, str] = {}
        publish_results: dict[str, PublishResult] = {}
        # #139: platforms this run holds a lease on but has not published yet.
        pending_leases: set[str] = set()
        lease_hash = ""
        publish_targets: list[Publisher] = []
        lease_claimed_at = 0.0
        skip_ai_stage = False
        temp_link = ""
        # #84: re-anchored just before vision runs; initialized here for scope.
        ai_stage_deadline = now_monotonic() + self._settings.ai_stage_timeout_seconds
        analysis = None
        spec = None
        dropbox_list_images_ms: int | None = None
        image_selection_ms: int | None = None
        vision_analysis_ms: int | None = None
        caption_generation_ms: int | None = None
        sidecar_write_ms: int | None = None
        publish_parallel_ms: int | None = None
        archive_ms: int | None = None
        selected_image = ""
        selected_hash = ""
        selected_content_hash = ""

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
            # 1. Select image
            # #139: preview and dry-publish publish nothing, so the file-based
            # "already posted" veto must not block them — ``--select X --preview``
            # stays the explicit override it has always been.
            sel = await self._select_image(select_filename, respect_posted_state=not preview_mode and not dry_publish)
            dropbox_list_images_ms = sel.dropbox_list_ms
            image_selection_ms = sel.selection_ms

            if sel.error:
                _log_timing()
                return WorkflowResult(
                    success=False,
                    image_name="",
                    caption="",
                    publish_results={},
                    archived=False,
                    error=sel.error,
                    correlation_id=correlation_id,
                )

            selected_image = sel.image_name
            selected_hash = sel.sha256
            selected_content_hash = sel.content_hash

            # 2. Save to temp and get temporary link
            suffix = os.path.splitext(selected_image)[1]
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(sel.content)
                tmp.flush()
                tmp_path = tmp.name
            with contextlib.suppress(Exception):
                os.chmod(tmp_path, 0o600)

            # #93 (PERF-2): the bytes are already in hand from the dedup
            # download — vision resizes them locally, so the presigned link
            # (a billed storage op on some backends) is only needed when the
            # legacy URL path is configured or preview wants a display URL.
            vision_uses_bytes = self.config.openai.vision_max_dimension > 0
            if preview_mode or not vision_uses_bytes:
                temp_link = await self.storage.get_temporary_link(
                    self.config.storage_paths.image_folder, selected_image
                )
            analysis_source: str | bytes = sel.content if vision_uses_bytes else temp_link

            # #139: claim the publish lease BEFORE the AI stage. Claiming it after
            # meant a crash in between left a permanently leased row (the image
            # could never be published again), and a double-click paid for a full
            # vision + caption run before discovering it owned nothing.
            enabled_publishers = [p for p in self.publishers if p.is_enabled()]
            lease_hash = selected_content_hash or selected_hash
            will_publish = (
                self.config.features.publish_enabled
                and bool(enabled_publishers)
                and not self.config.content.debug
                and not dry_publish
                and not preview_mode
            )
            publish_targets = list(enabled_publishers)
            if will_publish and self._publish_store is not None and lease_hash:
                # Stamped before the claim round-trip so the release fence below
                # can only ever over-estimate how fresh this run's lease is.
                lease_claimed_at = now_monotonic()
                try:
                    publish_targets = await self._claim_publish_targets(
                        lease_hash, enabled_publishers, publish_results, correlation_id
                    )
                except PublishStoreUnavailableError:
                    # AC8 (#186): fail closed. A store is configured but could not
                    # be reached, so nothing is leased and nothing may be published.
                    # Not re-raised: the /publish call site reads success/error off
                    # the result, and the CLI maps success=False to exit 1.
                    _log_timing()
                    return WorkflowResult(
                        success=False,
                        image_name=selected_image,
                        caption="",
                        publish_results={},
                        archived=False,
                        error="publish_store_unavailable",
                        correlation_id=correlation_id,
                    )
                pending_leases = {p.platform_name for p in publish_targets}
                # Nothing left to publish: skip the AI stage entirely (it only
                # feeds the publish + sidecar path for this run).
                skip_ai_stage = not publish_targets

            # 3. Analyze image with vision AI (feature-gated)
            if self.config.features.analyze_caption_enabled and not skip_ai_stage:
                if not preview_mode:
                    log_json(
                        self.logger,
                        logging.INFO,
                        "vision_analysis_start",
                        image=selected_image,
                        correlation_id=correlation_id,
                    )
                analysis_start = now_monotonic()
                # #84: one shared deadline covers vision AND caption generation.
                ai_stage_deadline = now_monotonic() + self._settings.ai_stage_timeout_seconds
                try:
                    analysis, vision_usage = await asyncio.wait_for(
                        self.ai_service.analyzer.analyze(analysis_source),
                        timeout=max(0.05, ai_stage_deadline - now_monotonic()),
                    )
                except TimeoutError as exc:
                    raise AIServiceError("ai stage timeout") from exc
                vision_analysis_ms = elapsed_ms(analysis_start)
                if self._usage_meter and vision_usage:
                    await self._usage_meter.emit(vision_usage)
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
            else:
                log_json(
                    self.logger,
                    logging.INFO,
                    "feature_analyze_caption_skipped",
                    correlation_id=correlation_id,
                    reason="nothing left to publish" if skip_ai_stage else "FEATURE_ANALYZE_CAPTION=false",
                )

            # 4. Generate caption from analysis (feature-gated)
            specs = CaptionSpec.for_platforms(self.config)
            spec = next(iter(specs.values()))  # primary spec for backward compat
            caption = ""
            sd_caption = None
            platform_captions: dict[str, str] = {}
            # #147: per-platform operator captions win over the legacy single override.
            overrides = {p: c for p, c in (caption_overrides or {}).items() if c and c.strip()}
            if overrides:
                platform_captions = dict(overrides)
                caption = overrides.get("email") or next(iter(overrides.values()))
                sd_caption = None
                log_json(
                    self.logger,
                    logging.INFO,
                    "caption_overrides_used",
                    override_lengths={p: len(c) for p, c in overrides.items()},
                    ai_skipped=True,
                    correlation_id=correlation_id,
                )
            elif caption_override and caption_override.strip():
                caption = caption_override
                sd_caption = None
                log_json(
                    self.logger,
                    logging.INFO,
                    "caption_override_used",
                    override_length=len(caption),
                    ai_skipped=True,
                    correlation_id=correlation_id,
                )
            elif self.config.features.analyze_caption_enabled and not skip_ai_stage:
                if analysis is None:
                    raise AIServiceError("Vision analysis is None but caption generation is enabled")
                if not preview_mode:
                    log_json(self.logger, logging.INFO, "caption_generation_start", correlation_id=correlation_id)
                caption_start = now_monotonic()
                if self.config.openai.sd_caption_enabled and self.config.openai.sd_caption_single_call_enabled:
                    log_json(self.logger, logging.INFO, "sd_caption_start", correlation_id=correlation_id)
                # PUB-035: Fetch caption history for context intelligence
                caption_history: dict[str, list[str]] | list[str] | None = None
                history_cfg = get_static_config().ai_prompts.caption_history
                # Caption history is DB-only post-cleanup. When no caption_store
                # is configured we pass None — the storage-scan fallback was
                # removed because it double-listed the folder on every workflow
                # and added 8 extra GETs per publish on the hot path.
                if self._caption_store is not None:
                    try:
                        db_history = await self._caption_store.fetch_recent_by_platform(
                            self._tenant,
                            platforms=list(specs.keys()),
                            limit=history_cfg.window_size,
                        )
                        caption_history = db_history
                        history_count = sum(len(v) for v in db_history.values()) if db_history else 0
                        log_json(
                            self.logger,
                            logging.INFO,
                            "caption_history_fetched",
                            source="db",
                            platforms=list(db_history.keys()) if db_history else [],
                            total_captions=history_count,
                            correlation_id=correlation_id,
                        )
                    except Exception:
                        log_json(
                            self.logger,
                            logging.WARNING,
                            "caption_history_fetch_failed",
                            correlation_id=correlation_id,
                            exc_info=True,
                        )

                # PUB-029/PUB-050: sample this image's voice examples when the feature is
                # enabled. Seeded per image so the same image always gets the same lines.
                voice_examples = None
                if self.config.features.voice_matching_enabled and self.config.content.voice_profile:
                    from publisher_v2.services.ai import sample_voice_examples

                    voice_examples = sample_voice_examples(
                        self.config.content.voice_profile,
                        seed_source=(selected_content_hash or selected_hash),
                        platform_tags=self.config.content.voice_profile_tags,
                        platforms=list(specs.keys()),
                    )

                # Use multi-platform generation if available, fall back to single-caption
                if hasattr(self.ai_service, "create_multi_caption_pair_from_analysis"):
                    try:
                        (
                            platform_captions,
                            sd_caption,
                            caption_usages,
                        ) = await asyncio.wait_for(
                            self.ai_service.create_multi_caption_pair_from_analysis(
                                analysis, specs, history=caption_history, voice_examples=voice_examples
                            ),
                            timeout=max(0.05, ai_stage_deadline - now_monotonic()),
                        )
                    except TimeoutError as exc:
                        raise AIServiceError("ai stage timeout") from exc
                    # Set primary caption from first platform
                    caption = next(iter(platform_captions.values()), "")
                else:
                    try:
                        caption, sd_caption, caption_usages = await asyncio.wait_for(
                            self.ai_service.create_caption_pair_from_analysis(analysis, spec),
                            timeout=max(0.05, ai_stage_deadline - now_monotonic()),
                        )
                    except TimeoutError as exc:
                        raise AIServiceError("ai stage timeout") from exc
                if self._usage_meter and caption_usages:
                    await self._usage_meter.emit_all(caption_usages)
                caption_generation_ms = elapsed_ms(caption_start)
                if not preview_mode:
                    log_json(
                        self.logger,
                        logging.INFO,
                        "caption_generated",
                        caption_length=len(caption),
                        platform_count=len(platform_captions),
                        correlation_id=correlation_id,
                    )
                if self.config.openai.sd_caption_enabled and self.config.openai.sd_caption_single_call_enabled:
                    log_json(
                        self.logger,
                        logging.INFO,
                        "sd_caption_complete",
                        has_sd=bool(sd_caption),
                        correlation_id=correlation_id,
                    )
                if analysis and sd_caption:
                    analysis = dataclasses.replace(analysis, sd_caption=sd_caption)
                if sd_caption and not self.config.content.debug and not dry_publish and not preview_mode:
                    from publisher_v2.services.sidecar import generate_and_upload_sidecar

                    model_version = getattr(self.ai_service.generator, "sd_caption_model", None) or getattr(
                        self.ai_service.generator, "model", ""
                    )
                    # Error already logged inside helper; suppress to continue workflow.
                    # sidecar_write_ms will remain None in workflow_timing on failure.
                    with contextlib.suppress(Exception):
                        sidecar_write_ms = int(
                            await generate_and_upload_sidecar(
                                storage=self.storage,
                                config=self.config,
                                filename=selected_image,
                                analysis=analysis,  # analysis is guaranteed non-None by the guard above
                                sd_caption=sd_caption,
                                model_version=str(model_version),
                                sha256=selected_hash,
                                correlation_id=correlation_id,
                                log_prefix="sidecar_upload",
                                platform_captions=platform_captions,
                            )
                        )
            else:
                log_json(
                    self.logger,
                    logging.INFO,
                    "feature_caption_generation_skipped",
                    correlation_id=correlation_id,
                    reason="nothing left to publish" if skip_ai_stage else "FEATURE_ANALYZE_CAPTION=false",
                )

            # 5. Publish in parallel
            if self.config.features.publish_enabled:
                if enabled_publishers and not self.config.content.debug and not dry_publish and not preview_mode:
                    publish_start = now_monotonic()
                    context = self._build_publisher_context(analysis)
                    # #85/#139: the per-platform lease was already claimed above,
                    # before the AI stage, so a partial publish never double-posts
                    # and a web double-click publishes once.
                    # #83: render one variant per publisher we're actually about to
                    # call this run, up front, so no publisher ever mutates the
                    # shared temp file mid-gather.
                    variant_paths = await self._render_publish_variants(tmp_path, publish_targets)
                    # #139: from here on every target gets an explicit mark, so the
                    # finally-release must not also touch them. Cleared after variant
                    # rendering: a failure in there still releases the leases.
                    pending_leases = set()
                    results = await asyncio.gather(
                        *[
                            asyncio.wait_for(
                                p.publish(
                                    variant_paths.get(p.platform_name, tmp_path),
                                    format_caption(
                                        p.platform_name,
                                        platform_captions.get(p.platform_name, caption),
                                        smart_hashtags=self.config.features.smart_hashtags_enabled,
                                    ),
                                    context=context,
                                ),
                                timeout=self._settings.publish_timeout_for(p.platform_name),
                            )
                            for p in publish_targets
                        ],
                        return_exceptions=True,
                    )
                    publish_parallel_ms = elapsed_ms(publish_start)
                    for pub, res in zip(publish_targets, results, strict=True):
                        if isinstance(res, asyncio.TimeoutError):
                            # The cancelled to_thread upload may still complete
                            # upstream: record as unknown, never auto-retried.
                            pr = PublishResult(
                                success=False,
                                platform=pub.platform_name,
                                error="publish timeout",
                            )
                            await self._mark_publish(lease_hash, pub.platform_name, "unknown", error="publish timeout")
                        elif isinstance(res, BaseException):
                            from publisher_v2.services.publishers._sanitize import sanitize_publisher_error

                            # sanitize_publisher_error() already prepends type(exc).__name__.
                            detail = sanitize_publisher_error(res)
                            pr = PublishResult(success=False, platform=pub.platform_name, error=detail)
                            await self._mark_publish(lease_hash, pub.platform_name, "failed", error=detail)
                        else:
                            pr = res
                            status = "published" if res.success else "failed"
                            await self._mark_publish(
                                lease_hash, pub.platform_name, status, post_id=res.post_id, error=res.error
                            )
                        publish_results[pub.platform_name] = pr
                else:
                    for p in enabled_publishers:
                        publish_results[p.platform_name] = PublishResult(success=True, platform=p.platform_name)
                    if enabled_publishers:
                        publish_parallel_ms = 0
            else:
                log_json(
                    self.logger,
                    logging.INFO,
                    "feature_publish_skipped",
                    correlation_id=correlation_id,
                    reason="FEATURE_PUBLISH=false",
                )

            partial = False
            if publish_results:
                any_success = any(r.success for r in publish_results.values())
                all_success = all(r.success for r in publish_results.values())
                partial = any_success and not all_success
            else:
                any_success = self.config.content.debug if self.config.features.publish_enabled else False
                all_success = any_success

            # PUB-035: Update sidecar with published caption when caption_override was used
            if (
                any_success
                and (caption_override or overrides)
                and not sd_caption
                and not self.config.content.debug
                and not dry_publish
                and not preview_mode
            ):
                from publisher_v2.services.sidecar import update_sidecar_with_caption

                with contextlib.suppress(Exception):
                    sidecar_write_ms = int(
                        await update_sidecar_with_caption(
                            storage=self.storage,
                            folder=self.config.storage_paths.image_folder,
                            filename=selected_image,
                            published_caption=caption,
                            caption_edited=True,
                            correlation_id=correlation_id,
                            published_platform_captions=platform_captions or None,
                        )
                    )

            # Save published (formatted) captions to DB for caption history
            if (
                any_success
                # #139: a run that owned nothing skipped the AI stage, so there is
                # no caption to record — the run that did publish already stored it.
                and not skip_ai_stage
                and self._caption_store is not None
                and not self.config.content.debug
                and not dry_publish
                and not preview_mode
            ):
                try:
                    source = "manual_override" if (caption_override or overrides) else "ai_generated"
                    # Build the actual published text per platform (after format_caption)
                    # and track truncation info for GH #73 monitoring.
                    published_captions: dict[str, str] = {}
                    truncation_info: dict[str, tuple[bool, int | None]] = {}
                    for p in enabled_publishers:
                        raw = platform_captions.get(p.platform_name, caption)
                        formatted = format_caption(
                            p.platform_name, raw, smart_hashtags=self.config.features.smart_hashtags_enabled
                        )
                        published_captions[p.platform_name] = formatted
                        if len(formatted) < len(raw):
                            truncation_info[p.platform_name] = (True, len(raw))

                    caption_model = getattr(getattr(self.ai_service, "generator", None), "model", None)
                    saved = await self._caption_store.save_captions_batch(
                        tenant=self._tenant,
                        captions_by_platform=published_captions,
                        image_filename=selected_image,
                        image_sha256=selected_hash or None,
                        correlation_id=correlation_id,
                        caption_source=source,
                        model_version=str(caption_model) if caption_model else None,
                        truncation_info=truncation_info or None,
                    )
                    log_json(
                        self.logger,
                        logging.INFO,
                        "caption_history_saved",
                        platforms=list(published_captions.keys()),
                        rows_saved=saved,
                        truncated_platforms=list(truncation_info.keys()),
                        correlation_id=correlation_id,
                    )
                except Exception:  # noqa: S110 — non-critical, don't break workflow
                    log_json(
                        self.logger,
                        logging.WARNING,
                        "caption_history_save_failed",
                        correlation_id=correlation_id,
                    )

            # 6. Persist "already posted" state BEFORE archive. If the process
            # crashes between publish and archive, the next workflow run still
            # sees the hash in the posted set and won't re-publish. The image
            # stays in the source folder until a (manual) re-run completes
            # archiving — preferable to double-posting on every platform.
            # #85: with a publish store, per-platform records own retry logic —
            # only a fully published image enters the file-based posted set, so
            # a partial publish stays selectable for the retry run. Without a
            # store, keep the legacy any-success semantics (file state has no
            # per-platform granularity; not saving would double-post).
            record_posted = all_success if self._publish_store is not None else any_success
            if record_posted and not self.config.content.debug and not dry_publish and not preview_mode:
                if selected_hash:
                    with contextlib.suppress(OSError):
                        save_posted_hash(selected_hash)
                if selected_content_hash:
                    with contextlib.suppress(OSError):
                        save_posted_content_hash(selected_content_hash)

            # 7. Archive if any success and not debug
            archived = False
            if (
                all_success
                and self.config.content.archive
                and not self.config.content.debug
                and not dry_publish
                and not preview_mode
            ):
                archive_start = now_monotonic()
                try:
                    await self.storage.archive_image(
                        self.config.storage_paths.image_folder,
                        selected_image,
                        self.config.storage_paths.archive_folder,
                    )
                    archived = True
                except Exception:
                    # Idempotent archive: a previous run may have already moved
                    # the file (state-saved-then-crash before archive completed
                    # on disk). Log and continue rather than retrying — the
                    # image will not be re-published thanks to the saved hash.
                    log_json(
                        self.logger,
                        logging.WARNING,
                        "workflow_archive_failed",
                        correlation_id=correlation_id,
                        image=selected_image,
                        exc_info=True,
                    )
                archive_ms = elapsed_ms(archive_start)
            elif any_success and not preview_mode and not dry_publish:
                if partial:
                    skip_reason = "partial_publish"
                elif not self.config.content.archive:
                    skip_reason = "content.archive=false"
                elif self.config.content.debug:
                    skip_reason = "content.debug=true"
                else:
                    skip_reason = "archive_preconditions_unmet"
                log_json(
                    self.logger,
                    logging.INFO,
                    "workflow_archive_skipped",
                    correlation_id=correlation_id,
                    image=selected_image,
                    reason=skip_reason,
                )

            # Final summary timing log for the workflow
            image_selection_ms = image_selection_ms or 0
            _log_timing()

            return WorkflowResult(
                success=all_success,
                partial=partial,
                image_name=selected_image,
                caption=caption,
                publish_results=publish_results,
                archived=archived,
                correlation_id=correlation_id,
                platform_captions=platform_captions,
                # Preview mode fields
                image_analysis=analysis if preview_mode else None,
                caption_spec=spec if preview_mode else None,
                source_url=temp_link if preview_mode else None,
                sha256=selected_hash if preview_mode else None,
                image_folder=self.config.storage_paths.image_folder if preview_mode else None,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):  # noqa: ASYNC240 — fast local FS check in finally cleanup
                with contextlib.suppress(Exception):
                    os.unlink(tmp_path)
            # #83: remove per-publisher variants alongside the source temp file.
            for variant in variant_paths.values():
                if variant != tmp_path and os.path.exists(variant):  # noqa: ASYNC240 — fast local FS check
                    with contextlib.suppress(Exception):
                        os.unlink(variant)
            # #139: any lease still pending here was never published — the run
            # aborted (exception or early return) between lease and publish, so
            # mark those rows failed and let the next run re-lease them. Last in
            # the block and shielded: a cancellation delivered at this await must
            # neither skip the temp-file cleanup above nor drop the release.
            held_for = now_monotonic() - lease_claimed_at if lease_claimed_at else 0.0
            if pending_leases and held_for >= self._settings.publish_lease_ttl_seconds:
                # #139: this run held the lease past the TTL, so another run may
                # have reclaimed it and be publishing right now. Marking it failed
                # would make it re-leasable mid-publish. Leave it to the TTL.
                log_json(
                    self.logger,
                    logging.WARNING,
                    "publish_lease_release_skipped_expired",
                    correlation_id=correlation_id,
                    platforms=sorted(pending_leases),
                    held_seconds=round(held_for, 1),
                )
                pending_leases = set()
            if pending_leases:
                release = asyncio.gather(
                    *[
                        self._mark_publish(lease_hash, platform, "failed", error="run aborted before publish (#139)")
                        for platform in sorted(pending_leases)
                    ]
                )
                try:
                    await asyncio.shield(release)
                except asyncio.CancelledError:
                    # Let the release finish (it is shielded), then re-raise:
                    # swallowing the cancellation here turned an aborted run into
                    # a normal WorkflowResult and lost an outer asyncio.timeout.
                    await release
                    raise

            # PUB-045: flush R2 storage ops counter even in preview mode (real R2 costs).
            # PUB-047 #185: a cancellation delivered during the shielded lease release above
            # re-raises before this line, so that run's drained ops stay in the storage
            # counter until the periodic loop or the next run flushes them — the lease is
            # worth more than a few minutes of billing delay, and nothing is lost. Do not
            # reorder this ahead of the release to "fix" it.
            meter = getattr(self, "_storage_ops_meter", None)
            if meter is not None:
                await meter.flush()

    async def _claim_publish_targets(
        self,
        lease_hash: str,
        enabled_publishers: list[Publisher],
        publish_results: dict[str, PublishResult],
        correlation_id: str,
    ) -> list[Publisher]:
        """Lease platforms for this run (#85) and pre-fill publish_results.

        Already-published platforms are recorded as successes (they WERE
        published — a retry run can then complete the archive); platforms
        leased by another run or stuck in ``unknown`` are recorded as failures
        and never re-published automatically. PUB-047 #186: a store failure now
        fails *closed* — it raises :class:`PublishStoreUnavailableError` instead
        of falling back to publishing everywhere unleased.
        """
        store = self._publish_store
        if store is None:  # pragma: no cover — caller guards
            return list(enabled_publishers)
        to_claim: list[str] = []

        async def _claim() -> tuple[set[str], dict[str, datetime]]:
            nonlocal to_claim
            posted = await store.posted_platforms(self._tenant, lease_hash)
            to_claim = [p.platform_name for p in enabled_publishers if p.platform_name not in posted]
            return posted, await store.acquire_lease(self._tenant, lease_hash, to_claim)

        try:
            # One budget covers both round-trips. At the default 10s it fires well
            # before asyncpg's 30s command_timeout — that timeout is not redundant,
            # it still bounds CaptionStore and every other DB call that is not
            # wrapped in a claim budget, so don't "simplify" either one away.
            already_published, owned_tokens = await asyncio.wait_for(
                _claim(), timeout=self._settings.publish_claim_timeout_seconds
            )
        except Exception as exc:
            log_json(
                self.logger,
                logging.WARNING,
                "publish_store_unavailable",
                correlation_id=correlation_id,
                exc_info=True,
            )
            raise PublishStoreUnavailableError("publish store unavailable during lease claim") from exc
        # #139: the token each lease was stamped with, so a later mark can be
        # fenced against a lease this run no longer holds.
        self._lease_tokens.update(owned_tokens)
        owned = set(owned_tokens)
        blocked = set(to_claim) - owned
        for name in already_published:
            publish_results[name] = PublishResult(success=True, platform=name)
        for name in blocked:
            publish_results[name] = PublishResult(
                success=False,
                platform=name,
                error="publish lease unavailable (in progress or unknown state)",
            )
        if already_published or blocked:
            log_json(
                self.logger,
                logging.INFO,
                "publish_lease_summary",
                correlation_id=correlation_id,
                already_published=sorted(already_published),
                blocked=sorted(blocked),
                owned=sorted(owned),
            )
        return [p for p in enabled_publishers if p.platform_name in owned]

    async def _mark_publish(
        self,
        lease_hash: str,
        platform: str,
        status: str,
        post_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Best-effort per-platform outcome record (#85). Never breaks the run."""
        if self._publish_store is None or not lease_hash:
            return
        try:
            await self._publish_store.mark(
                self._tenant,
                lease_hash,
                platform,
                status,
                post_id=post_id,
                error=error,
                lease_token=self._lease_tokens.get(platform),
            )
        except Exception:
            log_json(self.logger, logging.WARNING, "publish_record_mark_failed", platform=platform, exc_info=True)

    async def _render_publish_variants(self, tmp_path: str, publishers: list[Publisher]) -> dict[str, str]:
        """Render one resized variant per publisher before the publish gather (#83).

        Widths come from platform_limits.yaml (``resize_width_px``); platforms
        without a width (e.g. email) get the untouched source path. Publishers
        never resize — the same shared temp file used to be rewritten to 1280
        and 1080 concurrently while email attached it mid-write.
        """
        from publisher_v2.utils.images import ensure_max_width

        limits = get_static_config().platform_limits
        base, suffix = os.path.splitext(tmp_path)
        variants: dict[str, str] = {}
        for publisher in publishers:
            platform = publisher.platform_name
            width = getattr(getattr(limits, platform, None), "resize_width_px", None)
            if not width:
                variants[platform] = tmp_path
                continue
            out_path = f"{base}.{platform}{suffix}"
            try:
                await asyncio.to_thread(ensure_max_width, tmp_path, width, out_path)
                os.chmod(out_path, 0o600)  # noqa: ASYNC240 — fast local FS call
                variants[platform] = out_path
            except Exception:
                # A failed variant must not sink the publish — fall back to the
                # source path (pre-#83 behavior minus the concurrent rewrite).
                log_json(
                    self.logger,
                    logging.WARNING,
                    "publish_variant_render_failed",
                    platform=platform,
                )
                variants[platform] = tmp_path
        return variants

    def _build_publisher_context(self, analysis: ImageAnalysis | None) -> dict[str, Any] | None:
        if analysis is None:
            return None
        tags = analysis.tags
        context: dict[str, Any] = {"analysis_tags": tags} if tags is not None else {}

        if self.config.features.alt_text_enabled and analysis.alt_text:
            context["alt_text"] = analysis.alt_text

        return context or None

    async def _curate_image(
        self,
        filename: str,
        target_subfolder: str | None,
        *,
        action: str,
        preview_mode: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Internal helper for Keep/Remove-style curation actions.

        When preview_mode or dry_run is True, this prints a human-readable
        description of the intended move and performs no Dropbox operations.
        """
        if not target_subfolder:
            raise StorageError(f"Cannot {action} image {filename!r}: target subfolder is not configured")

        source_folder = self.config.storage_paths.image_folder

        if preview_mode or dry_run:
            # Non-destructive path (#96): no console printing here — the
            # orchestrator returns data; presentation belongs to the caller.
            log_json(
                self.logger,
                logging.INFO,
                "workflow_curation_preview",
                image=filename,
                action=action,
                source_folder=source_folder,
                target_subfolder=target_subfolder,
            )
            return

        # Live move via Dropbox server-side move.
        log_json(
            self.logger,
            logging.INFO,
            "workflow_curation_start",
            image=filename,
            action=action,
            source_folder=source_folder,
            target_subfolder=target_subfolder,
        )
        await self.storage.move_image_with_sidecars(source_folder, filename, target_subfolder)
        log_json(
            self.logger,
            logging.INFO,
            "workflow_curation_complete",
            image=filename,
            action=action,
            source_folder=source_folder,
            target_subfolder=target_subfolder,
        )

    async def keep_image(
        self,
        filename: str,
        *,
        preview_mode: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Move an image (and its sidecars) into the configured keep folder."""
        if not self.config.features.keep_enabled:
            raise StorageError("Keep feature is disabled via FEATURE_KEEP_CURATE toggle")
        await self._curate_image(
            filename=filename,
            target_subfolder=self.config.storage_paths.folder_keep,
            action="keep",
            preview_mode=preview_mode,
            dry_run=dry_run,
        )

    async def remove_image(
        self,
        filename: str,
        *,
        preview_mode: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Move an image (and its sidecars) into the configured remove folder."""
        if not self.config.features.remove_enabled:
            raise StorageError("Remove feature is disabled via FEATURE_REMOVE_CURATE toggle")
        await self._curate_image(
            filename=filename,
            target_subfolder=self.config.storage_paths.folder_remove,
            action="remove",
            preview_mode=preview_mode,
            dry_run=dry_run,
        )

    async def delete_image(
        self,
        filename: str,
        *,
        preview_mode: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Permanently delete an image (and its sidecars) from storage.

        This is a destructive operation and cannot be undone.
        """
        if not self.config.features.delete_enabled:
            raise StorageError("Delete feature is disabled via FEATURE_DELETE toggle")

        if preview_mode or dry_run:
            self.logger.info(f"[DRY RUN] Would delete image: {filename}")
            return

        self.logger.info(f"Deleting image permanently: {filename}")
        await self.storage.delete_file_with_sidecar(
            self.config.storage_paths.image_folder,
            filename,
        )
