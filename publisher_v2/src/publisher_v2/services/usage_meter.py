"""Fire-and-forget usage metering for orchestrated mode."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from publisher_v2.core.models import AIUsage
from publisher_v2.utils.logging import log_json

if TYPE_CHECKING:
    from publisher_v2.config.orchestrator_client import OrchestratorClient


class UsageMeter:
    """Emit AI token usage events to the orchestrator billing endpoint.

    All exceptions are caught and logged — metering never blocks the workflow.
    """

    def __init__(self, client: OrchestratorClient, tenant_id: str) -> None:
        self._client = client
        self._tenant_id = tenant_id
        self._logger = logging.getLogger("publisher_v2.metering")

    async def emit(self, usage: AIUsage, metric: str = "ai_tokens", unit: str = "tokens") -> None:
        """Fire-and-forget usage emission. Never raises."""
        try:
            await self._client.post_usage(
                tenant_id=self._tenant_id,
                metric=metric,
                quantity=usage.total_tokens,
                unit=unit,
                idempotency_key=usage.response_id,
                occurred_at=datetime.now(UTC).isoformat(),
                source="publisher",
            )
        except Exception:
            log_json(
                self._logger,
                logging.WARNING,
                "usage_metering_failed",
                metric=metric,
                quantity=usage.total_tokens,
                tenant_id=self._tenant_id,
            )

    async def emit_all(self, usages: list[AIUsage], metric: str = "ai_tokens", unit: str = "tokens") -> None:
        """Emit usage for all non-None, non-zero entries."""
        for u in usages:
            if u is not None and u.total_tokens > 0:
                await self.emit(u, metric=metric, unit=unit)
