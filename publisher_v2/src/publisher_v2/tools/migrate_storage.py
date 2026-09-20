"""Standalone CLI tool to migrate content from Dropbox to managed storage (R2).

Usage:
    uv run python -m publisher_v2.tools.migrate_storage \
        --source-folder "/My Photos" \
        --target-prefix "tenant/instance"

Not part of the normal publish workflow — this is an operator migration action.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

from publisher_v2.services.storage_protocol import ObjectStorageProtocol
from publisher_v2.utils.logging import log_json, setup_logging

logger = logging.getLogger("publisher_v2.tools.migrate_storage")

REQUIRED_ENV_VARS = [
    "DROPBOX_APP_KEY",
    "DROPBOX_APP_SECRET",
    "MIGRATE_DROPBOX_REFRESH_TOKEN",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_BUCKET_NAME",
]


@dataclass
class MigrationResult:
    """Summary of a migration run."""

    copied: int = 0
    skipped: int = 0
    errors: int = 0
    total_files: int = 0
    total_bytes: int = 0

    @property
    def exit_code(self) -> int:
        return 1 if self.errors > 0 else 0


def validate_env_vars() -> list[str]:
    """Return list of error messages for missing required env vars."""
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    return [f"Missing required environment variable: {var}" for var in missing]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the migration tool."""
    parser = argparse.ArgumentParser(
        description="Migrate images from Dropbox to managed storage (R2).",
    )
    parser.add_argument("--source-folder", required=True, help="Dropbox root folder path (e.g. /My Photos)")
    parser.add_argument("--target-prefix", required=True, help="Managed storage key prefix (e.g. tenant/instance)")
    parser.add_argument("--archive-folder", default=None, help="Dropbox archive folder (copies archive too)")
    parser.add_argument("--dry-run", action="store_true", help="List what would be copied; no writes")
    parser.add_argument("--limit", type=int, default=None, help="Copy at most N images")
    parser.add_argument(
        "--no-resume", dest="resume", action="store_false", default=True, help="Disable resume/skip existing"
    )
    return parser.parse_args(argv)


async def _copy_sidecar(
    source: Any,
    target: Any,
    src_folder: str,
    filename: str,
    sidecar_key: str,
    only_if_missing: bool = False,
) -> None:
    """Copy one image's caption sidecar. Never fails the image it belongs to."""
    try:
        if only_if_missing and await target.exists(sidecar_key):
            return
        sidecar_data = await source.download_sidecar_if_exists(src_folder, filename)
        if sidecar_data is not None:
            await target.put_object(sidecar_key, sidecar_data, "text/plain; charset=utf-8")
    except Exception as exc:
        log_json(logger, logging.WARNING, "migration_sidecar_error", file=filename, error=str(exc))


async def run_migration(
    source: Any,
    target: ObjectStorageProtocol,
    source_folder: str,
    target_prefix: str,
    subfolders: list[str],
    dry_run: bool,
    limit: int | None,
    resume: bool = True,
) -> MigrationResult:
    """Core migration logic. Works with any storage objects implementing the required async methods."""
    result = MigrationResult()
    images_processed = 0

    # Build list of (source_subfolder, target_subfolder) pairs to migrate
    folder_pairs: list[tuple[str, str]] = [
        (source_folder, target_prefix),
    ]
    for sub in subfolders:
        folder_pairs.append((f"{source_folder.rstrip('/')}/{sub}", f"{target_prefix.rstrip('/')}/{sub}"))

    for src_folder, tgt_prefix in folder_pairs:
        try:
            images_with_hashes = await source.list_images_with_hashes(src_folder)
        except Exception:
            # Subfolder may not exist in Dropbox
            log_json(logger, logging.WARNING, "migration_subfolder_skip", folder=src_folder, reason="list_failed")
            continue

        for filename, _content_hash in images_with_hashes:
            if limit is not None and images_processed >= limit:
                break

            result.total_files += 1
            target_key = f"{tgt_prefix.rstrip('/')}/{filename}"

            if dry_run:
                # Dry-run: just count files and download to measure size
                try:
                    data = await source.download_image(src_folder, filename)
                    result.total_bytes += len(data)
                except Exception:
                    result.total_bytes += 0
                log_json(logger, logging.INFO, "migration_dry_run_file", file=filename, target_key=target_key)
                images_processed += 1
                continue

            # Resume: skip anything already in the target (#142).
            # This used to compare R2's ETag with Dropbox's content_hash — an
            # MD5-based value against a block-SHA256 one, so the skip branch was
            # dead and every re-run re-copied the whole library. Presence is the
            # semantic the tool wants; --no-resume forces a re-copy.
            stem = os.path.splitext(filename)[0]
            sidecar_key = f"{tgt_prefix.rstrip('/')}/{stem}.txt"
            if resume:
                try:
                    if await target.exists(target_key):
                        # The image landed on an earlier run; its sidecar is
                        # written after it, so a run interrupted in between left
                        # the sidecar behind. Copy it rather than skipping into
                        # a permanently caption-less object.
                        await _copy_sidecar(source, target, src_folder, filename, sidecar_key, only_if_missing=True)
                        result.skipped += 1
                        images_processed += 1
                        log_json(logger, logging.DEBUG, "migration_skip_existing", file=filename, target_key=target_key)
                        continue
                except Exception:  # noqa: S110
                    pass  # Existence unknown — proceed with the copy.

            # Download from source
            try:
                image_data = await source.download_image(src_folder, filename)
            except Exception as exc:
                result.errors += 1
                log_json(logger, logging.ERROR, "migration_download_error", file=filename, error=str(exc))
                images_processed += 1
                continue

            # Upload to target
            try:
                content_type = "image/jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "image/png"
                await target.put_object(target_key, image_data, content_type)
                result.total_bytes += len(image_data)
            except Exception as exc:
                result.errors += 1
                log_json(logger, logging.ERROR, "migration_upload_error", file=filename, error=str(exc))
                images_processed += 1
                continue

            await _copy_sidecar(source, target, src_folder, filename, sidecar_key)

            result.copied += 1
            images_processed += 1

            # Progress logging every 10 files
            if images_processed % 10 == 0:
                log_json(
                    logger,
                    logging.INFO,
                    "migration_progress",
                    copied=result.copied,
                    skipped=result.skipped,
                    errors=result.errors,
                    total=result.total_files,
                )

        if limit is not None and images_processed >= limit:
            break

    # Final summary. #142: the tool now goes through the metered protocol methods,
    # so drain the counter and report it — otherwise "every call is counted" has no
    # observable effect for an operator, and a resumed run's HEAD cost stays hidden.
    drain = getattr(target, "drain_ops_count", None)
    drained = drain() if callable(drain) else None
    storage_ops = drained if isinstance(drained, int) else None
    log_json(
        logger,
        logging.INFO,
        "migration_complete",
        copied=result.copied,
        skipped=result.skipped,
        errors=result.errors,
        total_files=result.total_files,
        total_bytes=result.total_bytes,
        dry_run=dry_run,
        storage_ops=storage_ops,
    )

    return result


def _build_source_storage(args: argparse.Namespace) -> Any:
    """Construct DropboxStorage from env vars (bypasses ApplicationConfig)."""
    from publisher_v2.config.schema import DropboxConfig
    from publisher_v2.services.storage import DropboxStorage

    config = DropboxConfig(
        app_key=os.environ["DROPBOX_APP_KEY"],
        app_secret=os.environ["DROPBOX_APP_SECRET"],
        refresh_token=os.environ["MIGRATE_DROPBOX_REFRESH_TOKEN"],
        image_folder=args.source_folder,
    )
    return DropboxStorage(config)


def _build_target_storage() -> Any:
    """Construct ManagedStorage from env vars (bypasses ApplicationConfig)."""
    from publisher_v2.config.schema import ManagedStorageConfig
    from publisher_v2.services.managed_storage import ManagedStorage

    config = ManagedStorageConfig(
        access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        bucket=os.environ["R2_BUCKET_NAME"],
        region=os.environ.get("R2_REGION", "auto"),
    )

    return ManagedStorage(config)


async def async_main() -> int:
    """Async entry point for the migration tool."""
    setup_logging(logging.INFO)

    args = parse_args()

    # Validate env vars
    errors = validate_env_vars()
    if errors:
        for err in errors:
            log_json(logger, logging.ERROR, "migration_env_error", error=err)
        return 1

    source = _build_source_storage(args)
    target = _build_target_storage()

    # Determine subfolders to migrate — use actual subfolder names from DropboxConfig defaults
    # or values derived from the source config. The standard subfolders are:
    # archive (default "archive"), keep (default "keep"), remove (default "reject")
    subfolders = ["archive", "keep", "reject"]

    # If --archive-folder is explicitly provided, include it as an additional source
    if args.archive_folder and args.archive_folder != args.source_folder:
        # archive_folder is an absolute Dropbox path; derive relative subfolder name
        rel = args.archive_folder.rstrip("/").rsplit("/", 1)[-1]
        if rel not in subfolders:
            subfolders.append(rel)

    result = await run_migration(
        source=source,
        target=target,
        source_folder=args.source_folder,
        target_prefix=args.target_prefix,
        subfolders=subfolders,
        dry_run=args.dry_run,
        limit=args.limit,
        resume=args.resume,
    )

    return result.exit_code


def main() -> None:
    """Synchronous entry point for `python -m publisher_v2.tools.migrate_storage`."""
    sys.exit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
