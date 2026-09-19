"""Storage factory — creates the appropriate storage backend from config."""

from __future__ import annotations

from publisher_v2.config.runtime_settings import RuntimeSettings
from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.services.storage_protocol import StorageProtocol


def create_storage(config: ApplicationConfig, settings: RuntimeSettings | None = None) -> StorageProtocol:
    """Return the appropriate storage backend based on config.

    Returns DropboxStorage when config.dropbox is set,
    ManagedStorage when config.managed is set.

    ``settings`` carries the already-parsed :class:`RuntimeSettings` so backends
    built on a request path do not re-read the environment (#143).
    """
    if config.managed is not None:
        from publisher_v2.services.managed_storage import ManagedStorage

        return ManagedStorage(config.managed, settings=settings)

    if config.dropbox is not None:
        from publisher_v2.services.storage import DropboxStorage

        return DropboxStorage(config.dropbox)

    raise ValueError("No storage provider configured")
