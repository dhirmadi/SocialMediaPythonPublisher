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
from typing import TYPE_CHECKING

from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.exceptions import AIServiceError, StorageError
from publisher_v2.core.models import CaptionSpec, PublishResult, WorkflowResult
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage_protocol import StorageProtocol

if TYPE_CHECKING:
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


class WorkflowOrchestrator:
    def __init__(
        self,
        config: ApplicationConfig,
        storage: StorageProtocol,
        ai_service: AIService,
        publishers: list[Publisher],
        usage_meter: UsageMeter | None = None,
    ):
        self.config = config
        self.storage = storage
        self.ai_service = ai_service
        self.publishers = publishers
        self._usage_meter = usage_meter
        self.logger = logging.getLogger("publisher_v2.workflow")

    async def _select_image(self, select_filename: str | None = None) -> _ImageSelection:
        """
        Select the next image to publish, applying dedup logic.

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
    ) -> WorkflowResult:
        correlation_id = str(uuid.uuid4())
        caption = ""
        tmp_path = ""
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
            sel = await self._select_image(select_filename)
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

            temp_link = await self.storage.get_temporary_link(self.config.storage_paths.image_folder, selected_image)

            # 3. Analyze image with vision AI (feature-gated)
            if self.config.features.analyze_caption_enabled:
                if not preview_mode:
                    log_json(
                        self.logger,
                        logging.INFO,
                        "vision_analysis_start",
                        image=selected_image,
                        correlation_id=correlation_id,
                    )
                analysis_start = now_monotonic()
                analysis, vision_usage = await self.ai_service.analyzer.analyze(temp_link)
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
                    reason="FEATURE_ANALYZE_CAPTION=false",
                )

            # 4. Generate caption from analysis (feature-gated)
            specs = CaptionSpec.for_platforms(self.config)
            spec = next(iter(specs.values()))  # primary spec for backward compat
            caption = ""
            sd_caption = None
            platform_captions: dict[str, str] = {}
            if caption_override and caption_override.strip():
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
            elif self.config.features.analyze_caption_enabled:
                if analysis is None:
                    raise AIServiceError("Vision analysis is None but caption generation is enabled")
                if not preview_mode:
                    log_json(self.logger, logging.INFO, "caption_generation_start", correlation_id=correlation_id)
                caption_start = now_monotonic()
                if self.config.openai.sd_caption_enabled and self.config.openai.sd_caption_single_call_enabled:
                    log_json(self.logger, logging.INFO, "sd_caption_start", correlation_id=correlation_id)
                # PUB-035: Fetch caption history for context intelligence
                caption_history: list[str] = []
                try:
                    from publisher_v2.services.ai import fetch_caption_history

                    history_cfg = get_static_config().ai_prompts.caption_history
                    caption_history = await fetch_caption_history(
                        self.storage,
                        self.config.storage_paths.image_folder,
                        window_size=history_cfg.window_size,
                        max_tokens_budget=history_cfg.max_tokens_budget,
                    )
                except Exception:  # noqa: S110 — graceful degradation per AC7
                    log_json(self.logger, logging.DEBUG, "caption_history_fetch_failed", correlation_id=correlation_id)

                # Use multi-platform generation if available, fall back to single-caption
                if hasattr(self.ai_service, "create_multi_caption_pair_from_analysis"):
                    (
                        platform_captions,
                        sd_caption,
                        caption_usages,
                    ) = await self.ai_service.create_multi_caption_pair_from_analysis(
                        analysis, specs, history=caption_history
                    )
                    # Set primary caption from first platform
                    caption = next(iter(platform_captions.values()), "")
                else:
                    caption, sd_caption, caption_usages = await self.ai_service.create_caption_pair_from_analysis(
                        analysis, spec
                    )
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
                            )
                        )
            else:
                log_json(
                    self.logger,
                    logging.INFO,
                    "feature_caption_generation_skipped",
                    correlation_id=correlation_id,
                    reason="FEATURE_ANALYZE_CAPTION=false",
                )

            # 5. Publish in parallel
            enabled_publishers = [p for p in self.publishers if p.is_enabled()]
            publish_results: dict[str, PublishResult] = {}
            if self.config.features.publish_enabled:
                if enabled_publishers and not self.config.content.debug and not dry_publish and not preview_mode:
                    publish_start = now_monotonic()
                    results = await asyncio.gather(
                        *[
                            p.publish(
                                tmp_path,
                                format_caption(
                                    p.platform_name,
                                    platform_captions.get(p.platform_name, caption),
                                ),
                                context={"analysis_tags": analysis.tags} if analysis else None,
                            )
                            for p in enabled_publishers
                        ],
                        return_exceptions=True,
                    )
                    publish_parallel_ms = elapsed_ms(publish_start)
                    for pub, res in zip(enabled_publishers, results, strict=True):
                        if isinstance(res, BaseException):
                            publish_results[pub.platform_name] = PublishResult(
                                success=False, platform=pub.platform_name, error=str(res)
                            )
                        else:
                            publish_results[pub.platform_name] = res
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

            if publish_results:
                any_success = any(r.success for r in publish_results.values())
            else:
                any_success = self.config.content.debug if self.config.features.publish_enabled else False

            # PUB-035: Update sidecar with published caption when caption_override was used
            # This ensures caption history includes manually-edited captions
            if (
                any_success
                and caption_override
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
                        )
                    )

            # 6. Archive if any success and not debug
            archived = False
            if (
                any_success
                and self.config.content.archive
                and not self.config.content.debug
                and not dry_publish
                and not preview_mode
            ):
                archive_start = now_monotonic()
                await self.storage.archive_image(
                    self.config.storage_paths.image_folder, selected_image, self.config.storage_paths.archive_folder
                )
                archive_ms = elapsed_ms(archive_start)
                archived = True
                if selected_hash:
                    save_posted_hash(selected_hash)
                if selected_content_hash:
                    save_posted_content_hash(selected_content_hash)
            elif any_success and not preview_mode and not dry_publish:
                if not self.config.content.archive:
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
                success=any_success,
                image_name=selected_image,
                caption=caption,
                publish_results=publish_results,
                archived=archived,
                correlation_id=correlation_id,
                platform_captions=platform_captions,
                # Preview mode fields
                image_analysis=analysis if preview_mode else None,
                caption_spec=spec if preview_mode else None,
                dropbox_url=temp_link if preview_mode else None,
                sha256=selected_hash if preview_mode else None,
                image_folder=self.config.storage_paths.image_folder if preview_mode else None,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):  # noqa: ASYNC240 — fast local FS check in finally cleanup
                with contextlib.suppress(Exception):
                    os.unlink(tmp_path)

    async def _curate_image(
        self,
        filename: str,
        target_subfolder: str | None,
        *,
        action: str,
        preview_mode: bool = False,
        dry_run: bool = False,
    ) -> None:
        """
        Internal helper for Keep/Remove-style curation actions.

        When preview_mode or dry_run is True, this prints a human-readable
        description of the intended move and performs no Dropbox operations.
        """
        if not target_subfolder:
            raise StorageError(f"Cannot {action} image {filename!r}: target subfolder is not configured")

        source_folder = self.config.storage_paths.image_folder

        if preview_mode or dry_run:
            # Non-destructive path: print preview-only description.
            from publisher_v2.utils.preview import print_curation_action

            print_curation_action(
                filename=filename,
                source_folder=source_folder,
                target_subfolder=target_subfolder,
                action=action,
            )
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
        """
        Move an image (and its sidecars) into the configured keep folder.
        """
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
        """
        Move an image (and its sidecars) into the configured remove folder.
        """
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
        """
        Permanently delete an image (and its sidecars) from storage.

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
