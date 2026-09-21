"""Publisher interface every platform implementation inherits.

Concrete publishers live beside this module (telegram, email, instagram) and
are assembled by ``build_publishers``; the orchestrator only ever sees this
interface.
"""

from abc import ABC, abstractmethod

from publisher_v2.core.models import PublishResult


class Publisher(ABC):
    """Abstract base for a single publishing target.

    Implementations are constructed with their own config and an enabled flag,
    and are expected to be safe to hold across a whole workflow run.
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the stable platform key used in results, logs and config lookups."""
        ...

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return True when this publisher is switched on and fully configured.

        The orchestrator skips disabled publishers, so this must not do I/O.
        """
        ...

    @abstractmethod
    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        """Publish the image at ``image_path`` with ``caption`` and report the outcome.

        Implementations must not raise for expected failures: return a
        ``PublishResult`` with ``success=False`` and an error string that
        carries no credentials. ``context`` holds optional per-platform extras
        (e.g. tags, recipients) and may be ignored.
        """
        ...
