from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from typing import List

from publisher_v2.config.loader import load_application_config
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.publishers.email import EmailPublisher
from publisher_v2.services.publishers.telegram import TelegramPublisher
from publisher_v2.services.publishers.instagram import InstagramPublisher
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.utils.logging import setup_logging, log_json
from publisher_v2.utils import preview as preview_utils
from publisher_v2.utils.captions import format_caption, build_metadata_phase1, build_metadata_phase2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Social Media Publisher V2")
    parser.add_argument("--config", required=True, help="Path to INI configuration file")
    parser.add_argument("--env", required=False, help="Optional path to .env file")
    parser.add_argument("--debug", action="store_true", help="Override debug mode to True")
    parser.add_argument("--select", required=False, help="Select a specific filename to post")
    parser.add_argument(
        "--dry-publish",
        action="store_true",
        help="Run full pipeline but skip actual platform publishing and archive",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show what will be published without taking any actions (human-readable output)",
    )
    return parser.parse_args()


async def main_async() -> int:
    args = parse_args()
    
    # Preview mode uses minimal logging (suppress JSON logs)
    if args.preview:
        setup_logging(logging.WARNING)
    else:
        setup_logging(logging.INFO)
    
    logger = logging.getLogger("publisher_v2")

    cfg = load_application_config(args.config, args.env)
    if args.debug:
        cfg.content.debug = True

    storage = DropboxStorage(cfg.dropbox)
    analyzer = VisionAnalyzerOpenAI(cfg.openai)
    generator = CaptionGeneratorOpenAI(cfg.openai)
    ai_service = AIService(analyzer, generator)

    publishers: List[Publisher] = [
        TelegramPublisher(cfg.telegram, cfg.platforms.telegram_enabled),
        EmailPublisher(cfg.email, cfg.platforms.email_enabled),
        InstagramPublisher(cfg.instagram, cfg.platforms.instagram_enabled),
    ]

    # Preview mode: show header
    if args.preview:
        preview_utils.print_preview_header()
        preview_utils.print_config_summary(
            vision_model=cfg.openai.vision_model,
            caption_model=cfg.openai.caption_model,
            config_file=args.config,
        )

    orchestrator = WorkflowOrchestrator(cfg, storage, ai_service, publishers)
    
    # Execute workflow (preview implies dry_publish)
    result = await orchestrator.execute(
        select_filename=args.select,
        dry_publish=args.dry_publish or args.preview,
        preview_mode=args.preview
    )
    
    # Preview mode: show results
    if args.preview:
        if not result.success:
            preview_utils.print_error(result.error or "Unknown error")
            return 1
        
        # Show image details
        preview_utils.print_image_details(
            filename=result.image_name,
            folder=result.image_folder or cfg.dropbox.image_folder,
            sha256=result.sha256 or "unknown",
            dropbox_url=result.dropbox_url or "unknown",
            is_new=True,
        )
        
        # Show vision analysis
        if result.image_analysis:
            preview_utils.print_vision_analysis(
                analysis=result.image_analysis,
                model=analyzer.model,
            )
        
        # Show caption
        if result.caption_spec:
            hashtag_count = result.caption.count('#')
            preview_utils.print_caption(
                caption=result.caption,
                spec=result.caption_spec,
                model=generator.model,
                hashtag_count=hashtag_count,
            )
            # Show caption sidecar content (sd_caption + metadata)
            if result.image_analysis and getattr(result.image_analysis, "sd_caption", None):
                created_iso = (
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                )
                model_version = getattr(generator, "sd_caption_model", None) or getattr(generator, "model", "")
                db_meta = await storage.get_file_metadata(cfg.dropbox.image_folder, result.image_name)
                phase1 = build_metadata_phase1(
                    image_file=result.image_name,
                    sha256=result.sha256 or "",
                    created_iso=created_iso,
                    sd_caption_version="v1.0",
                    model_version=str(model_version),
                    dropbox_file_id=db_meta.get("id"),
                    dropbox_rev=db_meta.get("rev"),
                )
                meta = dict(phase1)
                if cfg.captionfile.extended_metadata_enabled:
                    meta.update(build_metadata_phase2(result.image_analysis))
                preview_utils.print_caption_sidecar_preview(result.image_analysis.sd_caption, meta)
        
        # Show platform preview with formatted captions
        platform_captions = {}
        for pub in publishers:
            if pub.is_enabled():
                platform_captions[pub.platform_name] = format_caption(pub.platform_name, result.caption)
        
        # Compute email subject preview if email is enabled
        email_subject = None
        email_caption_target = None
        email_subject_mode = None
        if cfg.platforms.email_enabled and cfg.email:
            email_caption_formatted = platform_captions.get("email", result.caption)
            # Build subject similar to EmailPublisher
            prefix_map = {"normal": "", "private": "Private: ", "avatar": "Avatar: "}
            email_subject_mode = (cfg.email.subject_mode or "normal").lower()
            prefix = prefix_map.get(email_subject_mode, "")
            email_caption_target = (cfg.email.caption_target or "subject").lower()
            if email_caption_target == "subject" or email_caption_target == "both":
                email_subject = f"{prefix}{email_caption_formatted}"
            else:
                email_subject = f"{prefix}Photo upload"

        preview_utils.print_platform_preview(
            publishers=publishers,
            caption=result.caption,
            platform_captions=platform_captions,
            email_subject=email_subject,
            email_caption_target=email_caption_target,
            email_subject_mode=email_subject_mode,
        )
        
        # Show email confirmation details (FetLife email path)
        if cfg.platforms.email_enabled and cfg.email:
            tags_sample = None
            if result.image_analysis:
                # lightweight normalization to preview tags
                raw = result.image_analysis.tags or []
                sample = []
                for t in raw:
                    t = t.strip().lower().lstrip("#")
                    t = "".join(ch if ch.isalnum() or ch == " " else " " for ch in t)
                    t = " ".join(t.split())
                    if t and t not in sample:
                        sample.append(t)
                tags_sample = sample[: cfg.email.confirmation_tags_count]
            preview_utils.print_email_confirmation_preview(
                enabled=True,
                to_sender=cfg.email.confirmation_to_sender,
                tags_count=cfg.email.confirmation_tags_count,
                tags_sample=tags_sample,
                nature=cfg.email.confirmation_tags_nature,
            )
        
        # Show footer
        preview_utils.print_preview_footer()
        return 0
    
    # Normal mode: JSON logging
    log_json(
        logger,
        logging.INFO,
        "workflow_complete",
        success=result.success,
        image=result.image_name,
        archived=result.archived,
        correlation_id=result.correlation_id,
        results={k: v.__dict__ for k, v in result.publish_results.items()},
    )
    return 0 if result.success else 1


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()


