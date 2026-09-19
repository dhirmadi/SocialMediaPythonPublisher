import asyncio
import logging
from typing import Any

from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired, LoginRequired, TwoFactorRequired

from publisher_v2.config.schema import InstagramConfig
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.models import PublishResult
from publisher_v2.services.instagram_session import (
    SessionStore,
    build_session_store,
    challenge_backoff_until,
)
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.logging import log_json, log_publisher_publish, now_monotonic

logger = logging.getLogger("publisher_v2.publishers.instagram")


class InstagramPublisher(Publisher):
    """Instagram publisher with a persistent session (#94, standalone mode).

    One ``Client`` per publisher instance; stored settings (device fingerprint,
    uuids, cookies) are restored via ``set_settings`` so the fingerprint stays
    stable across restarts and password logins happen once per session
    lifetime. Challenges never trigger an immediate password retry — the
    publish fails and a 24h backoff is recorded.
    """

    def __init__(
        self,
        config: InstagramConfig | None,
        enabled: bool,
        *,
        session_store: SessionStore | None = None,
        tenant: str = "default",
    ):
        self._config = config
        self._enabled = enabled and config is not None
        self._limits = get_static_config().service_limits.instagram
        self._tenant = tenant
        self._store = session_store or build_session_store(getattr(config, "session_file", None))
        self._client: Client | None = None
        self._logged_in = False

    @property
    def platform_name(self) -> str:
        return "instagram"

    def is_enabled(self) -> bool:
        return self._enabled

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = Client()
            self._client.delay_range = [
                self._limits.delay_min_seconds,
                self._limits.delay_max_seconds,
            ]
        return self._client

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        if not self._enabled or not self._config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")

        config = self._config  # bind to local for type narrowing
        start = now_monotonic()

        from datetime import UTC, datetime

        blocked_until = await self._store.get_blocked_until(self._tenant)
        if blocked_until is not None and datetime.now(UTC) < blocked_until:
            error = f"instagram challenge backoff active until {blocked_until.isoformat()}"
            log_publisher_publish(logger, self.platform_name, start, success=False, error=error)
            return PublishResult(success=False, platform=self.platform_name, error=error)

        try:
            if not self._logged_in:
                settings = await self._store.load(self._tenant)

                def _login() -> dict[str, Any]:
                    client = self._get_client()
                    if settings:
                        # Restores device fingerprint + uuids + cookies, so the
                        # login below reuses the session instead of a fresh
                        # password auth with a new device.
                        client.set_settings(settings)
                    client.login(config.username, config.password)
                    return dict(client.get_settings())

                new_settings = await asyncio.to_thread(_login)
                self._logged_in = True
                # Persist immediately after login (#94 item 4).
                await self._store.save(self._tenant, new_settings)

            def _upload() -> tuple[str, dict[str, Any]]:
                client = self._get_client()
                media = client.photo_upload(image_path, caption)
                post_id = str(media.id) if hasattr(media, "id") else ""
                return post_id, dict(client.get_settings())

            post_id, latest_settings = await asyncio.to_thread(_upload)
            await self._store.save(self._tenant, latest_settings)
            log_publisher_publish(logger, self.platform_name, start, success=True)
            return PublishResult(success=True, platform=self.platform_name, post_id=post_id or None)
        except (ChallengeRequired, TwoFactorRequired, LoginRequired) as exc:
            # Never loop password logins into a challenge — back off 24h.
            until = challenge_backoff_until()
            await self._store.set_blocked_until(self._tenant, until)
            self._logged_in = False
            self._client = None
            error = f"instagram challenge/auth required ({type(exc).__name__}); backing off until {until.isoformat()}"
            log_json(
                logger,
                logging.WARNING,
                "instagram_challenge_backoff",
                error_type=type(exc).__name__,
                blocked_until=until.isoformat(),
            )
            log_publisher_publish(logger, self.platform_name, start, success=False, error=error)
            return PublishResult(success=False, platform=self.platform_name, error=error)
        except Exception as exc:
            from publisher_v2.services.publishers._sanitize import sanitize_publisher_error

            safe = sanitize_publisher_error(exc)
            log_publisher_publish(logger, self.platform_name, start, success=False, error=safe)
            return PublishResult(success=False, platform=self.platform_name, error=safe)
