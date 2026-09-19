import asyncio
import logging
from collections.abc import Callable
from typing import Any

from instagrapi import Client
from instagrapi.exceptions import ChallengeError, ChallengeRequired, LoginRequired, TwoFactorRequired

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


def _reraise(_client: Client, exc: Exception) -> None:
    """instagrapi ``handle_exception`` hook: surface every error to the publisher.

    Without it, instagrapi auto-resolves a ChallengeRequired inside the request
    (#133) — prompting ``input()`` for a code or raising ChallengeError siblings —
    so the 24h backoff below would never see it.
    """
    raise exc


def _has_session_identity(settings: dict[str, Any]) -> bool:
    """True when restored settings carry a user id, i.e. instagrapi's login() will
    reuse the session instead of doing a password login (#133)."""
    auth = settings.get("authorization_data") or {}
    cookies = settings.get("cookies") or {}
    return bool(
        settings.get("user_id")
        or (isinstance(auth, dict) and auth.get("ds_user_id"))
        or (isinstance(cookies, dict) and cookies.get("ds_user_id"))
    )


def _carry_device(client: Client, stale: dict[str, Any]) -> None:
    """Carry the device fingerprint (not the dead cookies) onto a fresh Client (#133).

    ``set_device`` does not recompute the User-Agent, so it is set explicitly —
    the stored one, or "" to derive it from the carried device.
    """
    if stale.get("uuids"):
        client.set_uuids(stale["uuids"])
    if stale.get("device_settings"):
        client.set_device(stale["device_settings"])
        client.set_user_agent(stale.get("user_agent") or "")


def _no_interactive_challenge_code(username: str, choice: object) -> str:
    """Never read a challenge code from stdin on a server (#133)."""
    raise ChallengeRequired("instagram challenge requires a code; not resolvable unattended")


class InstagramPublisher(Publisher):
    """Instagram publisher with a persistent session (#94, standalone mode).

    One ``Client`` per publisher instance; stored settings (device fingerprint,
    uuids, cookies) are restored via ``set_settings`` so the fingerprint stays
    stable across restarts and password logins happen once per session
    lifetime. An expired session (``LoginRequired`` on upload) is cleared and
    relogged once (#133). Challenges never trigger an immediate password
    retry — the publish fails and a 24h backoff is recorded.
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
            self._client.handle_exception = _reraise
            self._client.challenge_code_handler = _no_interactive_challenge_code
        return self._client

    async def _password_login(self, login_fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Run one password login with the 24h backoff written FIRST (#133).

        The block is lifted only when the login returns. Any failure (BadPassword,
        throttling, an unexpected error) or a cancellation from the workflow's
        publish timeout therefore leaves the backoff in place, so a failed
        password login can never repeat on every publish.
        """
        if not await self._store.set_blocked_until(self._tenant, challenge_backoff_until()):
            # Fail closed: without a stored backoff a failed login could repeat on
            # every publish, so do not risk the password login at all.
            raise RuntimeError("instagram backoff could not be stored; skipping password login")
        settings = await asyncio.to_thread(login_fn)
        await self._store.set_blocked_until(self._tenant, None)
        return settings

    async def _relogin(self, config: Any) -> dict[str, Any]:
        """#133: the stored session expired — clear it and log in once on a fresh Client.

        The device fingerprint (uuids, device settings) is carried over; only the
        dead cookies/authorization go. A brand-new device is what triggers challenges.
        """
        log_json(logger, logging.INFO, "instagram_session_expired_relogin")
        stale = await self._store.load(self._tenant) or {}
        await self._store.clear(self._tenant)
        self._client = None
        self._logged_in = False

        def _do() -> dict[str, Any]:
            client = self._get_client()
            _carry_device(client, stale)
            client.login(config.username, config.password, relogin=True)
            return dict(client.get_settings())

        settings = await self._password_login(_do)
        self._logged_in = True
        return settings

    async def _back_off(self, exc: BaseException, start: float) -> PublishResult:
        """Never loop password logins into a challenge — record a 24h backoff."""
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

        relogged = False
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
                    if settings and _has_session_identity(settings):
                        # #133: login() is a no-op while a user id is restored, so
                        # check the session with a cheap private request. A dead
                        # session would otherwise fail later at rupload with
                        # PhotoNotUpload, which never triggers the relogin.
                        client.get_timeline_feed()
                    return dict(client.get_settings())

                if settings and _has_session_identity(settings):
                    try:
                        new_settings = await asyncio.to_thread(_login)
                    except LoginRequired:
                        relogged = True
                        new_settings = await self._relogin(config)
                else:
                    new_settings = await self._password_login(_login)
                self._logged_in = True
                # Persist immediately after login (#94 item 4).
                await self._store.save(self._tenant, new_settings)

            def _upload() -> tuple[str, dict[str, Any]]:
                client = self._get_client()
                media = client.photo_upload(image_path, caption)
                post_id = str(media.id) if hasattr(media, "id") else ""
                return post_id, dict(client.get_settings())

            try:
                post_id, latest_settings = await asyncio.to_thread(_upload)
            except LoginRequired:
                if relogged:
                    raise
                relogged = True
                await self._store.save(self._tenant, await self._relogin(config))
                post_id, latest_settings = await asyncio.to_thread(_upload)
            await self._store.save(self._tenant, latest_settings)
            log_publisher_publish(logger, self.platform_name, start, success=True)
            return PublishResult(success=True, platform=self.platform_name, post_id=post_id or None)
        except (ChallengeError, TwoFactorRequired, LoginRequired) as exc:
            return await self._back_off(exc, start)
        except Exception as exc:
            # A failed password login already left its 24h backoff (see
            # _password_login); after a successful login this is an ordinary failure.
            from publisher_v2.services.publishers._sanitize import sanitize_publisher_error

            safe = sanitize_publisher_error(exc)
            log_publisher_publish(logger, self.platform_name, start, success=False, error=safe)
            return PublishResult(success=False, platform=self.platform_name, error=safe)
