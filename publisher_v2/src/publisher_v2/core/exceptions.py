class SocialMediaPublisherError(Exception):
    """Base exception for the application."""


class ConfigurationError(SocialMediaPublisherError):
    """Configuration is invalid or missing."""


class StorageError(SocialMediaPublisherError):
    """Error accessing cloud storage."""


class AIServiceError(SocialMediaPublisherError):
    """AI analysis or caption generation failed."""


class PublishingError(SocialMediaPublisherError):
    """Error publishing to platform."""


