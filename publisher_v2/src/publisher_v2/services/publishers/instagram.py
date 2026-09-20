import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeError,
    ChallengeRequired,
    ClientConnectionError,
    ClientIncompleteReadError,
    ClientRequestTimeout,
    LoginRequired,
    TwoFactorRequired,
)

from publisher_v2.config.schema import InstagramConfig
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.models import PublishResult
from publisher_v2.services.instagram_session import (
    TRANSIENT_BACKOFF_HOURS,
    SessionStore,
    build_session_store,
    challenge_backoff_until,
    transient_backoff_until,
)
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.logging import log_json, log_publisher_publish, now_monotonic

# A failed-login backoff write must not outlive the publish deadline it is
# already past; the pre-written 24h block is the safe fallback.
_BACKOFF_WRITE_TIMEOUT_SECONDS = 5.0

# A login that never got an answer. Everything NOT listed here is treated as a
# verdict from Instagram and keeps the full backoff — see _password_login.
_TRANSIENT_LOGIN_ERRORS = (
    ClientConnectionError,
    ClientRequestTimeout,
    # Unreachable from the private-request login path (it is raised by
    # public_request), kept as defence in depth.
    ClientIncompleteReadError,
    asyncio.CancelledError,
)

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


# The parts of a stored session that identify the *device*, not the login.
# Instagram challenges a familiar account arriving from an unfamiliar device,
# so these have to outlive the dead credentials they were stored beside.
_DEVICE_KEYS = (
    "uuids",
    "device_settings",
    "user_agent",
    # Sent as X-MID and the locale/country/timezone headers. Leaving these to
    # instagrapi's US/en_US defaults while carrying a UA whose locale segment
    # says otherwise is the device discontinuity this is meant to prevent.
    "mid",
    "country",
    "country_code",
    "locale",
    "timezone_offset",
)


def _device_fingerprint(stale: dict[str, Any]) -> dict[str, Any]:
    # `is not None`, not truthiness: timezone_offset 0 is UTC, a real value.
    return {key: stale[key] for key in _DEVICE_KEYS if stale.get(key) is not None and stale[key] != ""}


def _carry_device(client: Client, stale: dict[str, Any]) -> None:
    """Carry the device fingerprint (not the dead cookies) onto a fresh Client (#133).

    ``set_device`` does not recompute the User-Agent, so it is set explicitly —
    the stored one, or "" to derive it from the carried device.
    """
    if stale.get("uuids"):
        client.set_uuids(stale["uuids"])
    # Request context before the UA: set_locale rebuilds the UA from the
    # device, so applying it afterwards would discard the stored string.
    # Country AFTER locale: set_locale ends by calling set_country with the
    # locale's own region, which would otherwise overwrite a stored country
    # that disagrees with it.
    if stale.get("locale"):
        client.set_locale(stale["locale"])
    if stale.get("country"):
        client.set_country(stale["country"])
    if stale.get("country_code"):
        client.set_country_code(stale["country_code"])
    if stale.get("timezone_offset") is not None:
        client.set_timezone_offset(stale["timezone_offset"])
    if stale.get("mid"):
        client.mid = stale["mid"]
    if stale.get("device_settings"):
        client.set_device(stale["device_settings"])
    # Unconditionally, and after set_device: `""` makes instagrapi derive the UA
    # from the device just carried, so a fingerprint with device settings but no
    # stored UA still gets a UA describing THAT device. Skipping the call would
    # leave the UA derived at construction from the default device — a UA and a
    # device that describe different phones, which is worse than either alone.
    #
    # Suppressed: deriving renders a template over device_settings, so a stored
    # session with a truncated device dict raises KeyError. That would surface
    # as a login verdict and cost a 24h block without ever attempting the
    # login, on every publish. A default UA is survivable; that loop is not.
    with contextlib.suppress(KeyError):
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

    def _drop_client(self) -> None:
        """Stop using the Client a failed login touched.

        `asyncio.to_thread` cannot be cancelled: after a publish timeout the
        worker keeps running `login()` against this object, so the next publish
        must not share its `requests.Session`.
        """
        self._client = None
        self._logged_in = False

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
        try:
            settings = await asyncio.to_thread(login_fn)
        except _TRANSIENT_LOGIN_ERRORS as exc:
            # The login never reached a verdict: the network failed, or our own
            # publish timeout cancelled the task. Still blocked, so a failure
            # cannot repeat on every publish, but not for a day.
            self._drop_client()
            with contextlib.suppress(Exception):
                # Bounded: under cancellation the deadline has already passed
                # and no further cancel will arrive, so a hung store would
                # otherwise hold the task open indefinitely. The 24h block
                # written before the login stands if this cannot be shortened.
                await asyncio.wait_for(
                    self._store.set_blocked_until(self._tenant, transient_backoff_until()),
                    timeout=_BACKOFF_WRITE_TIMEOUT_SECONDS,
                )
            log_json(
                logger,
                logging.WARNING,
                "instagram_password_login_transient_failure",
                error_type=type(exc).__name__,
                backoff_hours=TRANSIENT_BACKOFF_HOURS,
            )
            raise
        except BaseException:
            # Anything else is Instagram giving a verdict — a challenge, 2FA,
            # bad credentials, throttling, an action block. Retrying within the
            # hour is what escalates to a challenge, so the full block stands.
            #
            # Deliberately an allow-list of transient errors rather than a list
            # of verdicts: the verdict list would have to be exhaustive to be
            # safe, and an instagrapi upgrade adding a new refusal would
            # silently reopen the hourly-retry hole. HTTP 429 is exactly that
            # case — ClientThrottledError is a direct ClientError, so no tuple
            # built from the throttling types catches it.
            #
            # BaseException, so KeyboardInterrupt and SystemExit pass through
            # here too. That is deliberate: the bare `raise` below re-raises
            # them untouched with the pre-written 24h block intact, and they
            # still get _drop_client(), which matters because the to_thread
            # worker may still be logging in against that Client.
            self._drop_client()
            raise
        await self._store.set_blocked_until(self._tenant, None)
        return settings

    async def _relogin(self, config: Any) -> dict[str, Any]:
        """#133: the stored session expired — clear it and log in once on a fresh Client.

        The device fingerprint (uuids, device settings, user agent) is carried
        over and re-persisted before the login is attempted; only the dead
        cookies/authorization go. A brand-new device is what triggers
        challenges, so the fingerprint has to survive a *failed* relogin too.
        """
        log_json(logger, logging.INFO, "instagram_session_expired_relogin")
        stale = await self._store.load(self._tenant) or {}

        # One atomic write, not clear-then-save. `save` replaces the file (or
        # the row) in a single step, so the device cannot be lost to a crash
        # between the two, nor to a `save` that swallows its own failure after
        # `clear` has already committed. If the relogin below fails, the device
        # is already safe and the next publish after the block reuses it
        # instead of logging in from a brand-new one.
        fingerprint = _device_fingerprint(stale)
        if fingerprint:
            await self._store.save(self._tenant, fingerprint)
        else:
            await self._store.clear(self._tenant)

        self._drop_client()

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
        if not await self._store.set_blocked_until(self._tenant, until):
            # Fail-closed everywhere else; here the publish has already failed,
            # so the only thing lost is the record. Say so loudly: without it
            # the next publish retries immediately, which is a narrower version
            # of the loop this issue removes.
            log_json(
                logger,
                logging.ERROR,
                "instagram_backoff_not_stored",
                detail="the challenge backoff could not be written; the next publish will retry immediately",
            )
        self._drop_client()
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
