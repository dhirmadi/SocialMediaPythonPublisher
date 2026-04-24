import logging
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, cast

from publisher_v2.config.credential_cache import CredentialCache, SingleFlight
from publisher_v2.config.credentials import (
    CredentialPayload,
    DropboxCredentials,
    ManagedStorageCredentials,
    OpenAICredentials,
    SMTPCredentials,
    TelegramCredentials,
)
from publisher_v2.config.host_utils import extract_tenant, normalize_host, validate_host
from publisher_v2.config.loader import load_application_config
from publisher_v2.config.orchestrator_client import OrchestratorClient, prefer_post_default
from publisher_v2.config.orchestrator_models import (
    OrchestratorConfigV1,
    OrchestratorConfigV2,
    OrchestratorRuntimeResponse,
)
from publisher_v2.config.runtime_cache import RuntimeConfigCache
from publisher_v2.config.schema import (
    ApplicationConfig,
    Auth0Config,
    CaptionFileConfig,
    ContentConfig,
    DropboxConfig,
    EmailConfig,
    FeaturesConfig,
    ManagedStorageConfig,
    ModelLifecycle,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
    TelegramConfig,
)
from publisher_v2.config.web_env import load_web_and_auth0_from_env
from publisher_v2.core.exceptions import (
    ConfigurationError,
    CredentialResolutionError,
    OrchestratorUnavailableError,
    TenantNotFoundError,
)
from publisher_v2.utils.logging import log_json


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """
    Per-request runtime configuration context.

    In env-first mode, tenant/host are synthetic; in orchestrator mode they come
    from the request host and orchestrator response.
    """

    host: str
    tenant: str
    config: ApplicationConfig
    # Optional metadata used by caches and observability
    schema_version: int | None = None
    config_version: str | None = None
    ttl_seconds: int | None = None
    credentials_refs: dict[str, str] | None = None


_source_logger = logging.getLogger("publisher_v2.config.source")

_SEVERITY_TO_LEVEL = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "critical": logging.ERROR,
}


def _map_lifecycle(lc_dict: dict[str, Any] | None, model_role: str) -> ModelLifecycle | None:
    """Map a raw lifecycle dict to a ModelLifecycle model, returning None on failure."""
    if lc_dict is None:
        return None
    try:
        return ModelLifecycle.model_validate(lc_dict)
    except Exception:
        log_json(_source_logger, logging.WARNING, "model_lifecycle_parse_error", model_role=model_role)
        return None


def emit_model_lifecycle_warnings(openai_cfg: OpenAIConfig) -> None:
    """Emit structured log warnings for model lifecycle advisories (PUB-040)."""
    for role, lc in [("vision", openai_cfg.vision_model_lifecycle), ("caption", openai_cfg.caption_model_lifecycle)]:
        if lc is None:
            continue
        level = _SEVERITY_TO_LEVEL.get(lc.severity, logging.WARNING)
        log_json(
            _source_logger,
            level,
            "model_lifecycle_warning",
            model_role=role,
            warning=lc.warning,
            shutdown_date=lc.shutdown_date,
            recommended_replacement=lc.recommended_replacement,
            severity=lc.severity,
        )


class ConfigSource(Protocol):
    async def get_config(self, host: str) -> RuntimeConfig: ...

    async def get_credentials(self, host: str, credentials_ref: str) -> dict[str, Any]: ...

    def is_orchestrated(self) -> bool: ...

    @property
    def orchestrator_client(self) -> OrchestratorClient | None: ...


class EnvConfigSource:
    """
    Env-first config source (single-tenant).

    Host is accepted for request plumbing, but config comes from Feature 021 loader.
    Optional STANDALONE_HOST enforces a single-host allowlist for safety.
    """

    def __init__(self) -> None:
        self._standalone_host = os.environ.get("STANDALONE_HOST")

        config_path = os.environ.get("CONFIG_PATH")
        env_path = os.environ.get("ENV_PATH")
        self._cfg = load_application_config(config_path, env_path)

    def is_orchestrated(self) -> bool:
        return False

    async def get_config(self, host: str) -> RuntimeConfig:
        h = normalize_host(host.strip())
        if self._standalone_host:
            allowed = normalize_host(self._standalone_host.strip())
            if h != allowed:
                raise TenantNotFoundError("Host not allowed in standalone mode")

        return RuntimeConfig(
            host=h,
            tenant="default",
            config=self._cfg,
            schema_version=None,
            config_version=None,
            ttl_seconds=None,
            credentials_refs=None,
        )

    @property
    def orchestrator_client(self) -> None:
        return None

    async def get_credentials(self, host: str, credentials_ref: str) -> dict[str, Any]:
        # Env-first mode does not support opaque refs; callers should use flat env vars.
        raise ConfigurationError("EnvConfigSource does not support credentials_ref resolution")


class OrchestratorConfigSource:
    """
    Orchestrator-backed config source (multi-tenant).

    Full implementation is added in Stories 02-05.
    """

    def __init__(self) -> None:
        self.base_url = os.environ.get("ORCHESTRATOR_BASE_URL")
        self.token = os.environ.get("ORCHESTRATOR_SERVICE_TOKEN")
        self.base_domain = os.environ.get("ORCHESTRATOR_BASE_DOMAIN") or "shibari.photo"

        if not self.base_url:
            raise ConfigurationError("ORCHESTRATOR_BASE_URL must be set for orchestrator config source")
        if not self.token:
            raise ConfigurationError("ORCHESTRATOR_SERVICE_TOKEN must be set when ORCHESTRATOR_BASE_URL is set")

        max_runtime = int(os.environ.get("RUNTIME_CONFIG_CACHE_MAX_SIZE") or "1000")
        self._runtime_cache: RuntimeConfigCache[str, RuntimeConfig] = RuntimeConfigCache(max_size=max_runtime)

        max_cred = int(os.environ.get("CREDENTIAL_CACHE_MAX_SIZE") or "5000")
        self._cred_cache: CredentialCache[tuple[str, str, str], CredentialPayload] = CredentialCache(max_size=max_cred)
        self._cred_latest_version: dict[tuple[str, str], str] = {}
        self._single_flight = SingleFlight()

        self._cred_cache_enabled = (os.environ.get("CREDENTIAL_CACHE_ENABLED") or "true").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self._cred_cache_ttl_seconds = int(os.environ.get("CREDENTIAL_CACHE_TTL_SECONDS") or "600")

        self._client = OrchestratorClient(
            base_url=self.base_url,
            service_token=self.token,
            prefer_post=prefer_post_default(),
        )

    @property
    def orchestrator_client(self) -> OrchestratorClient:
        return self._client

    def is_orchestrated(self) -> bool:
        return True

    async def get_config(self, host: str) -> RuntimeConfig:
        if not validate_host(host):
            raise TenantNotFoundError("Invalid host shape")
        h = normalize_host(host.strip())

        cached, fresh = self._runtime_cache.get(h)
        if cached and fresh:
            return cached

        request_id = str(uuid.uuid4())
        try:
            payload = await self._client.get_runtime_by_host(h, request_id=request_id)
            runtime = OrchestratorRuntimeResponse.model_validate(payload)
            if runtime.app_type != "publisher_v2":
                raise TenantNotFoundError("Host is not bound to publisher_v2")

            # schema v1 vs v2 config parsing
            schema_version = int(runtime.schema_version or 1)
            if schema_version == 1:
                cfg_v1 = OrchestratorConfigV1.model_validate(runtime.config)
                app_cfg, creds = await self._build_app_config_v1(h, runtime.tenant, cfg_v1)
            else:
                cfg_v2 = OrchestratorConfigV2.model_validate(runtime.config)
                app_cfg, creds = await self._build_app_config_v2(h, runtime.tenant, cfg_v2)

            # PUB-040: Emit lifecycle warnings on fresh fetch (not on cache hit)
            emit_model_lifecycle_warnings(app_cfg.openai)

            rc = RuntimeConfig(
                host=h,
                tenant=runtime.tenant,
                config=app_cfg,
                schema_version=schema_version,
                config_version=runtime.config_version,
                ttl_seconds=runtime.ttl_seconds,
                credentials_refs=creds,
            )

            self._runtime_cache.set(h, rc, ttl_seconds=runtime.ttl_seconds)
            return rc
        except TenantNotFoundError:
            raise
        except OrchestratorUnavailableError:
            # Serve stale when available
            if cached and not fresh:
                self._runtime_cache.mark_stale_served()
                return cached
            raise
        except Exception as exc:
            # Serve stale on unexpected parse issues only if we have cached
            if cached and not fresh:
                self._runtime_cache.mark_stale_served()
                return cached
            raise OrchestratorUnavailableError(f"Failed to load runtime config: {exc}") from exc

    async def get_credentials(self, host: str, credentials_ref: str) -> dict[str, Any]:
        if not validate_host(host):
            raise TenantNotFoundError("Invalid host shape")
        h = normalize_host(host.strip())
        tenant = extract_tenant(h, self.base_domain)

        async def _resolve() -> CredentialPayload:
            request_id = str(uuid.uuid4())
            data = await self._client.resolve_credentials(tenant, credentials_ref, request_id=request_id)
            provider = str(data.get("provider") or "")
            if provider == "dropbox":
                return DropboxCredentials.model_validate(data)
            if provider == "openai":
                return OpenAICredentials.model_validate(data)
            if provider == "telegram":
                return TelegramCredentials.model_validate(data)
            if provider == "smtp":
                return SMTPCredentials.model_validate(data)
            if provider == "managed":
                return ManagedStorageCredentials.model_validate(data)
            raise CredentialResolutionError(f"Unsupported provider: {provider}")

        # Single-flight key should not include version (unknown until resolved)
        sf_key = f"{tenant}:{credentials_ref}"

        if self._cred_cache_enabled:
            latest_version = self._cred_latest_version.get((tenant, credentials_ref))
            if latest_version:
                cached = self._cred_cache.get((tenant, credentials_ref, latest_version))
                if cached is not None:
                    return cast(dict[str, Any], cached.model_dump())

        payload: CredentialPayload = await self._single_flight.do(sf_key, _resolve)

        if self._cred_cache_enabled:
            self._cred_latest_version[(tenant, credentials_ref)] = payload.version
            self._cred_cache.set(
                (tenant, credentials_ref, payload.version),
                payload,
                ttl_seconds=self._cred_cache_ttl_seconds,
            )

        return cast(dict[str, Any], payload.model_dump())

    def check_connectivity_host(self) -> str:
        """Return a valid host used for readiness connectivity checks."""
        bd = (self.base_domain or "shibari.photo").lstrip(".")
        return f"healthcheck.{bd}"

    async def check_connectivity(self) -> None:
        """
        Readiness check: validate we can reach orchestrator.
        A 404 is acceptable and indicates connectivity.
        """
        host = self.check_connectivity_host()
        request_id = str(uuid.uuid4())
        try:
            await self._client.get_runtime_by_host(host, request_id=request_id)
        except TenantNotFoundError:
            return

    def _resolve_path(self, root: str, value: str | None, default_suffix: str) -> str:
        """Join ``root`` with a relative segment, or accept an already-rooted S3 key prefix.

        Orchestrator commonly sends full bucket-relative paths for ``archive``/``keep``/``remove``
        (e.g. ``tenant/root/archive``). Those must not be prefixed with ``root`` again.
        """
        r = root.strip().rstrip("/")
        if value is None or not str(value).strip():
            candidate = f"{r}/{default_suffix.lstrip('/')}"
        else:
            s = str(value).strip()
            candidate = s if s.startswith("/") or (r and (s == r or s.startswith(f"{r}/"))) else f"{r}/{s.lstrip('/')}"
        if ".." in candidate.split("/"):
            raise ConfigurationError("Storage path contains '..' which is not allowed")
        return candidate

    async def _build_app_config_v1(
        self, host: str, tenant: str, cfg: OrchestratorConfigV1
    ) -> tuple[ApplicationConfig, dict[str, str]]:
        """
        Schema v1: features+storage required; all other blocks default/disabled.
        """
        features = FeaturesConfig(**cfg.features.model_dump())
        # v1 fallback: disable AI features
        features.analyze_caption_enabled = False

        storage = cfg.storage
        if storage.provider not in ("dropbox", "managed"):
            raise ConfigurationError(f"Unsupported storage provider: {storage.provider}")

        root = storage.paths.root
        archive = self._resolve_path(root, storage.paths.archive, "archive")
        keep = self._resolve_path(root, storage.paths.keep, "keep")
        remove = self._resolve_path(root, storage.paths.remove, "reject")

        storage_paths = StoragePathConfig(
            image_folder=root, archive_folder=archive, folder_keep=keep, folder_remove=remove
        )

        creds_refs: dict[str, str] = {"storage": storage.credentials_ref}
        dropbox_cfg: DropboxConfig | None = None
        managed_cfg: ManagedStorageConfig | None = None

        if storage.provider == "managed":
            data = await self.get_credentials(host, storage.credentials_ref)
            ms_creds = ManagedStorageCredentials.model_validate(data)
            managed_cfg = ManagedStorageConfig(
                access_key_id=ms_creds.access_key_id,
                secret_access_key=ms_creds.secret_access_key,
                endpoint_url=ms_creds.endpoint_url,
                bucket=ms_creds.bucket,
                region=ms_creds.region,
            )
        else:
            data = await self.get_credentials(host, storage.credentials_ref)
            db_creds = DropboxCredentials.model_validate(data)
            dropbox_cfg = DropboxConfig(
                app_key=os.environ["DROPBOX_APP_KEY"],
                app_secret=os.environ["DROPBOX_APP_SECRET"],
                refresh_token=db_creds.refresh_token,
                image_folder=root,
                archive_folder=archive,
                folder_keep=keep,
                folder_remove=remove,
            )

        # OpenAI config exists but has no api_key in v1 fallback
        openai_cfg = OpenAIConfig()

        platforms = PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False)
        content = ContentConfig(hashtag_string="", archive=True, debug=False)
        captionfile = CaptionFileConfig(extended_metadata_enabled=False, artist_alias=None)
        web_cfg, auth0_cfg = load_web_and_auth0_from_env()

        app_cfg = ApplicationConfig(
            dropbox=dropbox_cfg,
            managed=managed_cfg,
            storage_paths=storage_paths,
            openai=openai_cfg,
            platforms=platforms,
            features=features,
            telegram=None,
            instagram=None,
            email=None,
            content=content,
            captionfile=captionfile,
            web=web_cfg,
            auth0=auth0_cfg,
        )

        return app_cfg, creds_refs

    async def _build_app_config_v2(
        self, host: str, tenant: str, cfg: OrchestratorConfigV2
    ) -> tuple[ApplicationConfig, dict[str, str]]:
        """
        Schema v2: parse additional blocks and maintain forward-compatibility.
        """
        features = FeaturesConfig(**cfg.features.model_dump())

        storage = cfg.storage
        if storage.provider not in ("dropbox", "managed"):
            raise ConfigurationError(f"Unsupported storage provider: {storage.provider}")

        root = storage.paths.root
        archive = self._resolve_path(root, storage.paths.archive, "archive")
        keep = self._resolve_path(root, storage.paths.keep, "keep")
        remove = self._resolve_path(root, storage.paths.remove, "reject")

        storage_paths = StoragePathConfig(
            image_folder=root, archive_folder=archive, folder_keep=keep, folder_remove=remove
        )

        creds_refs: dict[str, str] = {"storage": storage.credentials_ref}
        dropbox_cfg: DropboxConfig | None = None
        managed_cfg: ManagedStorageConfig | None = None

        if storage.provider == "managed":
            data = await self.get_credentials(host, storage.credentials_ref)
            ms_creds = ManagedStorageCredentials.model_validate(data)
            managed_cfg = ManagedStorageConfig(
                access_key_id=ms_creds.access_key_id,
                secret_access_key=ms_creds.secret_access_key,
                endpoint_url=ms_creds.endpoint_url,
                bucket=ms_creds.bucket,
                region=ms_creds.region,
            )
        else:
            data = await self.get_credentials(host, storage.credentials_ref)
            db_creds = DropboxCredentials.model_validate(data)
            dropbox_cfg = DropboxConfig(
                app_key=os.environ["DROPBOX_APP_KEY"],
                app_secret=os.environ["DROPBOX_APP_SECRET"],
                refresh_token=db_creds.refresh_token,
                image_folder=root,
                archive_folder=archive,
                folder_keep=keep,
                folder_remove=remove,
            )

        # Publishers: only enabled entries should be considered
        enabled_pubs = [p for p in cfg.publishers if p.enabled]
        telegram_cfg: TelegramConfig | None = None
        email_cfg: EmailConfig | None = None

        telegram_enabled = False
        email_enabled = False

        for p in enabled_pubs:
            if p.type == "telegram" and not telegram_cfg:
                channel_id = str(p.config.get("channel_id") or "").strip()
                if channel_id:
                    telegram_enabled = True
                    telegram_cfg = TelegramConfig(bot_token=None, channel_id=channel_id)
                    if p.credentials_ref:
                        creds_refs["telegram"] = p.credentials_ref
            # FetLife uses shared email_server.password_ref
            if p.type == "fetlife" and not email_cfg and cfg.email_server and cfg.email_server.password_ref:
                recipient = str(p.config.get("recipient") or "").strip()
                if recipient and cfg.email_server.from_email:
                    email_enabled = True
                    conf = cfg.confirmation
                    email_cfg = EmailConfig(
                        sender=cfg.email_server.from_email,
                        recipient=recipient,
                        password=None,
                        smtp_server=cfg.email_server.host,
                        smtp_port=int(cfg.email_server.port),
                        confirmation_to_sender=bool(conf.confirmation_to_sender)
                        if conf is not None and conf.confirmation_to_sender is not None
                        else True,
                        confirmation_tags_count=int(conf.confirmation_tags_count)
                        if conf is not None and conf.confirmation_tags_count is not None
                        else 5,
                        confirmation_tags_nature=str(conf.confirmation_tags_nature)
                        if conf is not None and conf.confirmation_tags_nature is not None
                        else "short, lowercase, human-friendly topical nouns; no hashtags; no emojis",
                        caption_target=str(p.config.get("caption_target") or "subject"),
                        subject_mode=str(p.config.get("subject_mode") or "normal"),
                    )
                    creds_refs["smtp"] = cfg.email_server.password_ref

        platforms = PlatformsConfig(
            telegram_enabled=telegram_enabled,
            instagram_enabled=False,
            email_enabled=email_enabled,
        )

        # AI settings (non-secret). If missing, force-disable AI feature.
        openai_cfg = OpenAIConfig()
        if cfg.ai and cfg.ai.credentials_ref:
            creds_refs["openai"] = cfg.ai.credentials_ref
            if cfg.ai.vision_model:
                openai_cfg.vision_model = cfg.ai.vision_model
            if cfg.ai.caption_model:
                openai_cfg.caption_model = cfg.ai.caption_model
            if cfg.ai.system_prompt:
                openai_cfg.system_prompt = cfg.ai.system_prompt
            if cfg.ai.role_prompt:
                openai_cfg.role_prompt = cfg.ai.role_prompt
            if cfg.ai.sd_caption_enabled is not None:
                openai_cfg.sd_caption_enabled = bool(cfg.ai.sd_caption_enabled)
            if cfg.ai.sd_caption_single_call_enabled is not None:
                openai_cfg.sd_caption_single_call_enabled = bool(cfg.ai.sd_caption_single_call_enabled)
            if cfg.ai.sd_caption_model:
                openai_cfg.sd_caption_model = cfg.ai.sd_caption_model
            if cfg.ai.sd_caption_system_prompt:
                openai_cfg.sd_caption_system_prompt = cfg.ai.sd_caption_system_prompt
            if cfg.ai.sd_caption_role_prompt:
                openai_cfg.sd_caption_role_prompt = cfg.ai.sd_caption_role_prompt
            # PUB-040: Map lifecycle metadata
            openai_cfg.vision_model_lifecycle = _map_lifecycle(cfg.ai.vision_model_lifecycle, "vision")
            openai_cfg.caption_model_lifecycle = _map_lifecycle(cfg.ai.caption_model_lifecycle, "caption")
        else:
            features.analyze_caption_enabled = False

        cf = cfg.captionfile
        captionfile = CaptionFileConfig(
            extended_metadata_enabled=bool(cf.extended_metadata_enabled)
            if cf and cf.extended_metadata_enabled is not None
            else False,
            artist_alias=cf.artist_alias if cf else None,
        )

        ct = cfg.content
        content = ContentConfig(
            hashtag_string=ct.hashtag_string or "" if ct else "",
            archive=bool(ct.archive) if ct and ct.archive is not None else True,
            debug=bool(ct.debug) if ct and ct.debug is not None else False,
            voice_profile=ct.voice_profile if ct else None,
        )

        web_cfg, auth0_cfg = load_web_and_auth0_from_env()
        auth0_cfg = _apply_orchestrator_auth_policy(auth0_cfg, cfg)
        app_cfg = ApplicationConfig(
            dropbox=dropbox_cfg,
            managed=managed_cfg,
            storage_paths=storage_paths,
            openai=openai_cfg,
            platforms=platforms,
            features=features,
            telegram=telegram_cfg,
            instagram=None,
            email=email_cfg,
            content=content,
            captionfile=captionfile,
            web=web_cfg,
            auth0=auth0_cfg,
        )
        return app_cfg, creds_refs


def _apply_orchestrator_auth_policy(auth0_cfg: Auth0Config | None, cfg: OrchestratorConfigV2) -> Auth0Config | None:
    """
    In orchestrator mode, tenant runtime config may include an `auth` block. We use it to:
    - Enable/disable Auth0 login per tenant (`auth.enabled`)
    - Override the per-tenant admin allowlist (`auth.allowed_emails`)

    Auth0 OAuth client credentials remain global (env-based) in Publisher.
    """
    auth = getattr(cfg, "auth", None)
    if auth is None:
        # No auth policy provided by orchestrator; keep env behavior.
        return auth0_cfg

    if not bool(getattr(auth, "enabled", False)):
        # Explicitly disabled for this tenant.
        return None

    if auth0_cfg is None:
        # Tenant wants auth enabled but dyno has no Auth0 app config.
        raise ConfigurationError("Auth0 must be configured in env when orchestrator auth.enabled=true")

    allowed = [str(e).strip() for e in (getattr(auth, "allowed_emails", None) or []) if str(e).strip()]
    # Override allowlist (can be empty to effectively deny all).
    return auth0_cfg.model_copy(update={"admin_emails": ",".join(allowed)})


@lru_cache(maxsize=1)
def get_config_source() -> ConfigSource:
    """
    Factory for config sources.

    - If CONFIG_SOURCE=env: force env-first.
    - Else if ORCHESTRATOR_BASE_URL set: orchestrator mode.
    - Else: env-first.
    """
    override = (os.environ.get("CONFIG_SOURCE") or "").strip().lower()
    if override == "env":
        return EnvConfigSource()

    if os.environ.get("ORCHESTRATOR_BASE_URL"):
        return OrchestratorConfigSource()

    return EnvConfigSource()


def clear_config_source_cache() -> None:
    """Test helper."""
    get_config_source.cache_clear()
