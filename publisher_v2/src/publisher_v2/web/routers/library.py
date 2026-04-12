"""Admin Library API router — CRUD for managed storage objects.

Only active when the instance uses managed storage (config.managed is not None).
All endpoints require require_auth + require_admin.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import unicodedata
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from publisher_v2.config.features import resolve_library_enabled
from publisher_v2.utils.logging import log_json
from publisher_v2.web.auth import require_admin, require_auth
from publisher_v2.web.dependencies import get_request_service
from publisher_v2.web.service import WebImageService

logger = logging.getLogger("publisher_v2.web.library")

router = APIRouter(prefix="/api/library", tags=["library"])

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
VALID_TARGET_FOLDERS = {"keep", "remove", "archive", "root"}

# In-memory rate limit store: {cookie_value: [timestamp, ...]}
_upload_rate_limit: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX = 10  # uploads per window


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class LibraryObject(BaseModel):
    key: str
    size: int
    last_modified: str


class LibraryListResponse(BaseModel):
    objects: list[LibraryObject]
    cursor: str | None = None


class LibraryUploadResponse(BaseModel):
    key: str
    size: int


class LibraryDeleteResponse(BaseModel):
    deleted: str
    sidecar_deleted: bool


class LibraryMoveRequest(BaseModel):
    target_folder: str


class LibraryMoveResponse(BaseModel):
    moved: str
    destination: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_library_available(service: WebImageService) -> None:
    """Raise 404 if library is not available for this instance."""
    if service.config.managed is None or not resolve_library_enabled(service.config):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not available for Dropbox instances",
        )


def _get_max_upload_bytes() -> int:
    """Get max upload size in bytes from env (default 20 MB)."""
    raw = os.environ.get("LIBRARY_MAX_UPLOAD_MB", "20")
    try:
        mb = int(raw)
    except ValueError:
        mb = 20
    return mb * 1024 * 1024


def _sanitize_filename(filename: str) -> str:
    """Sanitize upload filename: strip path traversal, normalize unicode."""
    # Extract just the filename (no directory components)
    name = PurePosixPath(filename).name
    # Normalize unicode
    name = unicodedata.normalize("NFC", name)
    # Remove any remaining path separators
    name = name.replace("/", "").replace("\\", "")
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")
    return name


def _check_rate_limit(request: Request) -> None:
    """Check upload rate limit (10/minute per admin session)."""
    cookie_val = request.cookies.get("pv2_admin", "anonymous")
    now = time.time()

    if cookie_val not in _upload_rate_limit:
        _upload_rate_limit[cookie_val] = []

    # Prune old entries
    _upload_rate_limit[cookie_val] = [t for t in _upload_rate_limit[cookie_val] if now - t < _RATE_LIMIT_WINDOW]

    if len(_upload_rate_limit[cookie_val]) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Upload rate limit exceeded (max 10/minute)",
        )

    _upload_rate_limit[cookie_val].append(now)


async def _list_objects_from_storage(
    service: WebImageService, prefix: str, cursor: str | None, limit: int
) -> dict[str, Any]:
    """List objects from managed storage with size/metadata."""
    # Library endpoints only run for ManagedStorage (guarded by _check_library_available)
    storage: Any = service.storage
    bucket = storage._bucket

    def _list() -> dict[str, Any]:
        paginator = storage.client.get_paginator("list_objects_v2")
        params: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": limit}
        if cursor:
            params["StartAfter"] = cursor

        objects: list[dict[str, Any]] = []
        next_cursor: str | None = None

        for page in paginator.paginate(**params):
            for obj in page.get("Contents", []):
                objects.append(
                    {
                        "key": obj["Key"].rsplit("/", 1)[-1] if "/" in obj["Key"] else obj["Key"],
                        "size": obj.get("Size", 0),
                        "last_modified": str(obj.get("LastModified", "")),
                    }
                )
            # Only get first page up to limit
            if len(objects) >= limit:
                objects = objects[:limit]
                if page.get("Contents"):
                    last = page["Contents"][-1]
                    next_cursor = last["Key"]
                break

        if len(objects) == limit and next_cursor is None:
            # Check if there might be more
            next_cursor = objects[-1]["key"] if objects else None

        return {"objects": objects, "cursor": next_cursor}

    return await asyncio.to_thread(_list)


async def _upload_to_storage(service: WebImageService, filename: str, data: bytes, content_type: str) -> dict[str, Any]:
    """Upload file to managed storage."""
    storage: Any = service.storage
    folder = service.config.storage_paths.image_folder
    key = f"{folder.strip('/')}/{filename}".lstrip("/")

    def _upload() -> None:
        storage.client.put_object(
            Bucket=storage._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    await asyncio.to_thread(_upload)
    return {"key": key, "size": len(data)}


async def _delete_from_storage(service: WebImageService, filename: str) -> dict[str, Any]:
    """Delete image + sidecar from managed storage."""
    storage: Any = service.storage
    folder = service.config.storage_paths.image_folder
    key = f"{folder.strip('/')}/{filename}".lstrip("/")

    def _check_exists() -> bool:
        try:
            storage.client.head_object(Bucket=storage._bucket, Key=key)
            return True
        except Exception:
            return False

    exists = await asyncio.to_thread(_check_exists)
    if not exists:
        raise FileNotFoundError(f"File not found: {filename}")

    # Delete image
    def _delete() -> bool:
        storage.client.delete_object(Bucket=storage._bucket, Key=key)
        # Try to delete sidecar
        stem = os.path.splitext(filename)[0]
        sidecar_key = f"{folder.strip('/')}/{stem}.txt".lstrip("/")
        sidecar_deleted = False
        try:
            storage.client.head_object(Bucket=storage._bucket, Key=sidecar_key)
            storage.client.delete_object(Bucket=storage._bucket, Key=sidecar_key)
            sidecar_deleted = True
        except Exception:  # noqa: S110
            pass  # Sidecar may not exist
        return sidecar_deleted

    sidecar_deleted = await asyncio.to_thread(_delete)
    return {"deleted": filename, "sidecar_deleted": sidecar_deleted}


async def _move_in_storage(service: WebImageService, filename: str, target_folder: str) -> dict[str, Any]:
    """Move image + sidecar to target folder in managed storage."""
    storage: Any = service.storage
    paths = service.config.storage_paths
    source_folder = paths.image_folder

    # Resolve target
    if target_folder == "root":
        dest_folder = paths.image_folder
    elif target_folder == "archive":
        dest_folder = f"{source_folder.strip('/')}/{paths.archive_folder}"
    elif target_folder == "keep":
        dest_folder = f"{source_folder.strip('/')}/{paths.folder_keep or 'keep'}"
    elif target_folder == "remove":
        dest_folder = f"{source_folder.strip('/')}/{paths.folder_remove or 'reject'}"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid target_folder: {target_folder}")

    src_key = f"{source_folder.strip('/')}/{filename}".lstrip("/")
    dst_key = f"{dest_folder.strip('/')}/{filename}".lstrip("/")

    def _move() -> None:
        bucket = storage._bucket
        # Copy then delete
        storage.client.copy_object(Bucket=bucket, Key=dst_key, CopySource={"Bucket": bucket, "Key": src_key})
        storage.client.delete_object(Bucket=bucket, Key=src_key)
        # Move sidecar if exists
        stem = os.path.splitext(filename)[0]
        sidecar_src = f"{source_folder.strip('/')}/{stem}.txt".lstrip("/")
        sidecar_dst = f"{dest_folder.strip('/')}/{stem}.txt".lstrip("/")
        try:
            storage.client.copy_object(
                Bucket=bucket, Key=sidecar_dst, CopySource={"Bucket": bucket, "Key": sidecar_src}
            )
            storage.client.delete_object(Bucket=bucket, Key=sidecar_src)
        except Exception:  # noqa: S110
            pass  # Sidecar may not exist

    await asyncio.to_thread(_move)
    return {"moved": filename, "destination": target_folder}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/objects", response_model=LibraryListResponse)
async def list_objects(
    request: Request,
    prefix: str = "",
    cursor: str | None = None,
    limit: int = 50,
    service: WebImageService = Depends(get_request_service),
) -> LibraryListResponse:
    """List objects under instance prefix (paginated)."""
    await require_auth(request)
    require_admin(request)
    _check_library_available(service)

    # Clamp limit
    limit = min(max(1, limit), 200)

    # Build storage prefix
    base = service.config.storage_paths.image_folder.strip("/")
    storage_prefix = f"{base}/{prefix}/" if prefix and prefix in ("archive", "keep", "remove") else f"{base}/"

    result = await _list_objects_from_storage(service, storage_prefix, cursor, limit)
    return LibraryListResponse(**result)


@router.post("/upload", response_model=LibraryUploadResponse)
async def upload_file(
    request: Request,
    file: UploadFile,
    service: WebImageService = Depends(get_request_service),
) -> LibraryUploadResponse:
    """Upload image to managed storage."""
    await require_auth(request)
    require_admin(request)
    _check_library_available(service)

    # Validate MIME type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {content_type}. Allowed: {', '.join(ALLOWED_MIME_TYPES)}",
        )

    # Read file data
    data = await file.read()

    # Validate size
    max_bytes = _get_max_upload_bytes()
    if len(data) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({len(data)} bytes). Maximum: {max_mb} MB",
        )

    # Rate limit
    _check_rate_limit(request)

    # Sanitize filename
    filename = _sanitize_filename(file.filename or "upload.jpg")

    result = await _upload_to_storage(service, filename, data, content_type)
    log_json(logger, logging.INFO, "library_upload", filename=filename, size=len(data))
    return LibraryUploadResponse(**result)


@router.delete("/objects/{filename}", response_model=LibraryDeleteResponse)
async def delete_object(
    filename: str,
    request: Request,
    service: WebImageService = Depends(get_request_service),
) -> LibraryDeleteResponse:
    """Delete object + sidecar from managed storage."""
    await require_auth(request)
    require_admin(request)
    _check_library_available(service)

    try:
        result = await _delete_from_storage(service, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {filename}") from exc

    log_json(logger, logging.INFO, "library_delete", filename=filename)
    return LibraryDeleteResponse(**result)


@router.post("/objects/{filename}/move", response_model=LibraryMoveResponse)
async def move_object(
    filename: str,
    body: LibraryMoveRequest,
    request: Request,
    service: WebImageService = Depends(get_request_service),
) -> LibraryMoveResponse:
    """Move image + sidecar to target folder."""
    await require_auth(request)
    require_admin(request)
    _check_library_available(service)

    if body.target_folder not in VALID_TARGET_FOLDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target_folder: {body.target_folder}. Must be one of: {', '.join(VALID_TARGET_FOLDERS)}",
        )

    result = await _move_in_storage(service, filename, body.target_folder)
    log_json(logger, logging.INFO, "library_move", filename=filename, destination=body.target_folder)
    return LibraryMoveResponse(**result)
