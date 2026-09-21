"""Exception hierarchy for the publisher.

Everything raised deliberately by the application derives from
``SocialMediaPublisherError``, so a caller can catch that one type at the
boundary. Sub-hierarchies group failures by subsystem (config, storage, AI,
publishing) and the leaf types carry the retry semantics: a
``StorageAuthError`` or ``UsageMeteringError`` must not be retried, while
``OrchestratorUnavailableError`` may be.
"""


class SocialMediaPublisherError(Exception):
    """Base exception for the application."""


class ConfigurationError(SocialMediaPublisherError):
    """Configuration is invalid or missing."""


class UnsupportedSchemaError(ConfigurationError):
    """Orchestrator runtime schema version is no longer supported (#97 stage 4)."""


class TenantNotFoundError(SocialMediaPublisherError):
    """Tenant/host does not map to a valid publisher_v2 runtime."""


class OrchestratorUnavailableError(SocialMediaPublisherError):
    """Orchestrator dependency is unavailable (retryable)."""


class CredentialResolutionError(SocialMediaPublisherError):
    """Failed to resolve secret material by credentials_ref."""


class StorageError(SocialMediaPublisherError):
    """Error accessing cloud storage."""


class StorageAuthError(StorageError):
    """Storage authentication failed (e.g. expired refresh token) — non-retryable (#88)."""


class AIServiceError(SocialMediaPublisherError):
    """AI analysis or caption generation failed."""


class PublishingError(SocialMediaPublisherError):
    """Error publishing to platform."""


class PublishInProgressError(PublishingError):
    """A publish for this image is already running (#139)."""


class AlreadyPublishedError(PublishingError):
    """This image was already published and will not be published again (#139)."""


class PublishStoreUnavailableError(PublishingError):
    """The publish store could not be reached to claim a lease (PUB-047 #186).

    Deliberately fail-closed: with a store configured, a claim that raises or
    exceeds ``publish_claim_timeout_seconds`` aborts the run instead of
    publishing unleased.
    """


class CaptionCoverageError(PublishingError):
    """A per-platform caption dict does not cover exactly the enabled platforms (#147).

    Anything less lets a platform fall back to another platform's text — the
    truncated-copy-to-email bug #147 exists to close.
    """


class UsageMeteringError(SocialMediaPublisherError):
    """Usage metering ingest call failed (non-retryable)."""


class InsufficientBalanceError(CredentialResolutionError):
    """Workspace cannot afford this platform-billed credential."""
