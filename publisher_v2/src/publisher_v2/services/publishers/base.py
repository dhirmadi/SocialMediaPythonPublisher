from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from publisher_v2.core.models import PublishResult


class Publisher(ABC):
    @property
    @abstractmethod
    def platform_name(self) -> str:
        ...

    @abstractmethod
    def is_enabled(self) -> bool:
        ...

    @abstractmethod
    async def publish(self, image_path: str, caption: str, context: Optional[dict] = None) -> PublishResult:
        ...


