from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
import hashlib
from typing import Dict, List, Tuple

from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.core.exceptions import AIServiceError, PublishingError, StorageError
from publisher_v2.core.models import CaptionSpec, PublishResult, WorkflowResult
from publisher_v2.services.ai import AIService
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.state import load_posted_hashes, save_posted_hash
from publisher_v2.utils.captions import format_caption


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

    async def execute(self, select_filename: str | None = None, dry_publish: bool = False) -> WorkflowResult:
        correlation_id = str(uuid.uuid4())
        selected_image = ""
        caption = ""
        tmp_path = ""
        selected_hash = ""
        try:
            # 1. Select image (prefer unseen by sha256)
            images = await self.storage.list_images(self.config.dropbox.image_folder)
            if not images:
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

            posted_hashes = load_posted_hashes()
            random.shuffle(images)
            content = b""
            if select_filename:
                if select_filename not in images:
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

            temp_link = await self.storage.get_temporary_link(self.config.dropbox.image_folder, selected_image)

            # 3. Generate caption
            spec = CaptionSpec(
                platform="generic",
                style="minimal_poetic",
                hashtags=self.config.content.hashtag_string,
                max_length=2200,
            )
            caption = await self.ai_service.create_caption(temp_link, spec)

            # 4. Publish in parallel
            enabled_publishers = [p for p in self.publishers if p.is_enabled()]
            publish_results: Dict[str, PublishResult] = {}
            if enabled_publishers and not self.config.content.debug and not dry_publish:
                results = await asyncio.gather(
                    *[
                        p.publish(tmp_path, format_caption(p.platform_name, caption))
                        for p in enabled_publishers
                    ],
                    return_exceptions=True,
                )
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

            any_success = any(r.success for r in publish_results.values()) if publish_results else self.config.content.debug

            # 5. Archive if any success and not debug
            archived = False
            if any_success and self.config.content.archive and not self.config.content.debug and not dry_publish:
                await self.storage.archive_image(
                    self.config.dropbox.image_folder, selected_image, self.config.dropbox.archive_folder
                )
                archived = True
                if selected_hash:
                    save_posted_hash(selected_hash)

            return WorkflowResult(
                success=any_success,
                image_name=selected_image,
                caption=caption,
                publish_results=publish_results,
                archived=archived,
                correlation_id=correlation_id,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


