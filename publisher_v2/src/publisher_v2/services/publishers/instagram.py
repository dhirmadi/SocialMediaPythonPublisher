from __future__ import annotations

import asyncio
from typing import Optional

from instagrapi import Client

from publisher_v2.config.schema import InstagramConfig
from publisher_v2.core.models import PublishResult
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.images import ensure_max_width


class InstagramPublisher(Publisher):
    def __init__(self, config: Optional[InstagramConfig], enabled: bool):
        self._config = config
        self._enabled = enabled and config is not None

    @property
    def platform_name(self) -> str:
        return "instagram"

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str) -> PublishResult:
        if not self._enabled or not self._config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")

        try:
            processed_path = ensure_max_width(image_path, max_width=1080)

            def _upload() -> str:
                client = Client()
                client.delay_range = [1, 3]
                # Try session-based login first
                try:
                    client.load_settings(self._config.session_file)
                    client.login(self._config.username, self._config.password)
                    client.get_timeline_feed()
                except Exception:
                    # Fallback to fresh login and persist new session
                    client.login(self._config.username, self._config.password)
                    client.dump_settings(self._config.session_file)
                media = client.photo_upload(processed_path, caption)
                return str(media.id) if hasattr(media, "id") else ""

            post_id = await asyncio.to_thread(_upload)
            return PublishResult(success=True, platform=self.platform_name, post_id=post_id or None)
        except Exception as exc:
            return PublishResult(success=False, platform=self.platform_name, error=str(exc))



