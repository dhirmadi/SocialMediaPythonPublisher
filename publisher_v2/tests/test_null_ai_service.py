"""#144 item 3: NullAIService.generator fails loudly instead of being a bare None."""

from __future__ import annotations

import pytest

from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import ImageAnalysis


def _analysis() -> ImageAnalysis:
    return ImageAnalysis(description="d", mood="m", tags=["t"], nsfw=False, safety_labels=[])


class TestNullGenerator:
    """#144 item 3: NullAIService.generator was a bare None — a mis-gated call hit AttributeError."""

    async def test_generate_raises_ai_service_error(self) -> None:
        from publisher_v2.services.ai import NullAIService

        with pytest.raises(AIServiceError):
            await NullAIService.generator.generate(_analysis(), None)

    async def test_generate_multi_raises_ai_service_error(self) -> None:
        from publisher_v2.services.ai import NullAIService

        with pytest.raises(AIServiceError):
            await NullAIService.generator.generate_multi(_analysis(), [])

    async def test_the_sd_entry_points_raise_too(self) -> None:
        """sd_caption_enabled defaults to True, so this is what a mis-gated single-platform run calls first.

        PUB-051 review: generate_multi_with_sd is deleted (no production caller after AC4),
        so the single-platform generate_with_sd is the only sd entry point left.
        """
        from publisher_v2.services.ai import NullAIService

        with pytest.raises(AIServiceError):
            await NullAIService.generator.generate_with_sd(_analysis(), None)
