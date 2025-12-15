from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from publisher_v2.config.schema import ApplicationConfig
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.utils.captions import (
    build_metadata_phase1,
    build_metadata_phase2,
    build_caption_sidecar,
)
from publisher_v2.utils.logging import log_json, elapsed_ms, now_monotonic

logger = logging.getLogger("publisher_v2.services.sidecar")


async def generate_and_upload_sidecar(
    storage: DropboxStorage,
    config: ApplicationConfig,
    filename: str,
    analysis: ImageAnalysis,
    sd_caption: str,
    model_version: str,
    sha256: str = "",
    correlation_id: Optional[str] = None,
    log_prefix: str = "sidecar_upload",  # e.g. "web_sidecar_upload" or "sidecar_upload"
) -> float:
    """
    Generate and upload a caption sidecar file.
    
    Returns:
        float: Duration of the operation in milliseconds.
    """
    start_time = now_monotonic()
    
    try:
        created_iso = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        
        # 1. Get file metadata from Dropbox for ID/Rev linkage
        db_meta = await storage.get_file_metadata(config.dropbox.image_folder, filename)
        
        # 2. Build metadata
        phase1 = build_metadata_phase1(
            image_file=filename,
            sha256=sha256,
            created_iso=created_iso,
            sd_caption_version="v1.0",
            model_version=model_version,
            dropbox_file_id=db_meta.get("id"),
            dropbox_rev=db_meta.get("rev"),
            artist_alias=config.captionfile.artist_alias,
        )
        meta = dict(phase1)
        
        if config.captionfile.extended_metadata_enabled and analysis:
            phase2 = build_metadata_phase2(analysis)
            meta.update(phase2)
            
        # 3. Build content
        content = build_caption_sidecar(sd_caption, meta)
        
        # 4. Upload
        log_json(
            logger, 
            logging.INFO, 
            f"{log_prefix}_start", 
            image=filename, 
            correlation_id=correlation_id
        )
        
        await storage.write_sidecar_text(config.dropbox.image_folder, filename, content)
        
        duration = elapsed_ms(start_time)
        
        log_json(
            logger,
            logging.INFO,
            f"{log_prefix}_complete",
            image=filename,
            correlation_id=correlation_id,
            sidecar_write_ms=duration,
        )
        return duration
        
    except Exception as exc:
        duration = elapsed_ms(start_time)
        log_json(
            logger,
            logging.ERROR,
            f"{log_prefix}_error",
            image=filename,
            error=str(exc),
            correlation_id=correlation_id,
            sidecar_write_ms=duration,
        )
        # Re-raise so caller knows it failed (or handle per policy? 
        # Existing code caught exceptions and just logged error. 
        # But for 'WebImageService' we returned 'sidecar_written=False'.
        # For 'WorkflowOrchestrator' we caught and logged, continuing workflow.
        # So we should probably raise here and let caller decide, 
        # OR suppress and return 0.0?
        # Better to raise so caller can see the failure.
        raise

