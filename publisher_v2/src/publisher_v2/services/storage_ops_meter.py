"""PUB-045: Storage ops metering.

Drain the R2 operation counter from ``ManagedStorage`` and emit a single
``storage_ops_requests`` usage event to the orchestrator. Never raises.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from publisher_v2.utils.logging import log_json

if TYPE_CHECKING:
    from publisher_v2.config.orchestrator_client import OrchestratorClient
    from publisher_v2.services.managed_storage import ManagedStorage


class StorageOpsMeter:
    """Emit aggregated R2 storage ops counts to the orchestrator billing endpoint."""

    def __init__(
        self,
        client: OrchestratorClient,
        tenant_id: str,
        storage: ManagedStorage,
    ) -> None:
        self._client = client
        self._tenant_id = tenant_id
        self._storage = storage
        self._logger = logging.getLogger("publisher_v2.storage_ops_metering")

    async def flush(self) -> None:
        """Drain the counter and emit to the orchestrator. Never raises."""
        count = self._storage.drain_ops_count()
        if count <= 0:
            return
        try:
            now = datetime.now(UTC)
            await self._client.post_usage(
                tenant_id=self._tenant_id,
                metric="storage_ops_requests",
                quantity=count,
                unit="requests",
                idempotency_key=f"r2ops:{self._tenant_id}:{now.strftime('%Y-%m-%d')}:{now.strftime('%H')}",
                occurred_at=now.isoformat(),
                source="publisher_storage_ops",
            )
        except Exception:
            log_json(
                self._logger,
                logging.WARNING,
                "storage_ops_metering_failed",
                metric="storage_ops_requests",
                quantity=count,
                tenant_id=self._tenant_id,
            )
