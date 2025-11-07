from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from typing import Dict, List, Tuple

from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.core.exceptions import AIServiceError, PublishingError, StorageError
from publisher_v2.core.models import CaptionSpec, PublishResult, WorkflowResult
from publisher_v2.services.ai import AIService
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.services.publishers.base import Publisher


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

    async def execute(self) -> WorkflowResult:
        correlation_id = str(uuid.uuid4())
        selected_image = ""
        caption = ""
        tmp_path = ""
        try:
            # 1. Select random image
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

            selected_image = random.choice(images)

            # 2. Download image to a temp file and get temporary link
            content = await self.storage.download_image(self.config.dropbox.image_folder, selected_image)
            suffix = os.path.splitext(selected_image)[1]
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp.flush()
                tmp_path = tmp.name

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
            if enabled_publishers and not self.config.content.debug:
                results = await asyncio.gather(
                    *[p.publish(tmp_path, caption) for p in enabled_publishers], return_exceptions=True
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
            if any_success and self.config.content.archive and not self.config.content.debug:
                await self.storage.archive_image(
                    self.config.dropbox.image_folder, selected_image, self.config.dropbox.archive_folder
                )
                archived = True

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


