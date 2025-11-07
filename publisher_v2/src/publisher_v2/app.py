from __future__ import annotations

import argparse
import asyncio
import logging
from typing import List

from publisher_v2.config.loader import load_application_config
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.publishers.email import EmailPublisher
from publisher_v2.services.publishers.telegram import TelegramPublisher
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.utils.logging import setup_logging, log_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Social Media Publisher V2")
    parser.add_argument("--config", required=True, help="Path to INI configuration file")
    parser.add_argument("--env", required=False, help="Optional path to .env file")
    parser.add_argument("--debug", action="store_true", help="Override debug mode to True")
    return parser.parse_args()


async def main_async() -> int:
    args = parse_args()
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
        # InstagramPublisher could be added here in future
    ]

    orchestrator = WorkflowOrchestrator(cfg, storage, ai_service, publishers)
    result = await orchestrator.execute()
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


