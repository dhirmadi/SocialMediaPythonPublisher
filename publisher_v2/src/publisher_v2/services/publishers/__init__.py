from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.publishers.email import EmailPublisher
from publisher_v2.services.publishers.instagram import InstagramPublisher
from publisher_v2.services.publishers.telegram import TelegramPublisher


def build_publishers(config: ApplicationConfig) -> list[Publisher]:
    """Canonical factory for the publisher list, derived from application config."""
    return [
        TelegramPublisher(config.telegram, config.platforms.telegram_enabled),
        EmailPublisher(config.email, config.platforms.email_enabled),
        InstagramPublisher(config.instagram, config.platforms.instagram_enabled),
    ]
