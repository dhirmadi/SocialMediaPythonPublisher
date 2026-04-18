class SocialMediaPublisherError(Exception):
    """Base exception for the application."""


class ConfigurationError(SocialMediaPublisherError):
    """Configuration is invalid or missing."""


class TenantNotFoundError(SocialMediaPublisherError):
    """Tenant/host does not map to a valid publisher_v2 runtime."""


class OrchestratorUnavailableError(SocialMediaPublisherError):
    """Orchestrator dependency is unavailable (retryable)."""


class CredentialResolutionError(SocialMediaPublisherError):
    """Failed to resolve secret material by credentials_ref."""


class StorageError(SocialMediaPublisherError):
    """Error accessing cloud storage."""


class AIServiceError(SocialMediaPublisherError):
    """AI analysis or caption generation failed."""


class PublishingError(SocialMediaPublisherError):
    """Error publishing to platform."""


class UsageMeteringError(SocialMediaPublisherError):
    """Usage metering ingest call failed (non-retryable)."""


class InsufficientBalanceError(CredentialResolutionError):
    """Workspace cannot afford this platform-billed credential."""
