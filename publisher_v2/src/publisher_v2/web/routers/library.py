"""Admin Library API router — CRUD for managed storage objects.

Only active when the instance uses managed storage (config.managed is not None).
All endpoints require require_auth + require_admin.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import unicodedata
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from publisher_v2.config.runtime_settings import load_runtime_settings
from publisher_v2.config.schema import StoragePathConfig
from publisher_v2.services.storage_protocol import ObjectStorageProtocol
from publisher_v2.utils.logging import log_json
from publisher_v2.utils.memory_io import reader_over
from publisher_v2.web.auth import require_admin, require_auth
from publisher_v2.web.dependencies import get_request_service
from publisher_v2.web.service import WebImageService

logger = logging.getLogger("publisher_v2.web.library")

router = APIRouter(prefix="/api/library", tags=["library"])


def _resolved_folder_under_image_root(image_folder: str, configured: str) -> str:
    """Resolve a storage path that may be a short segment (``archive``) or full key prefix."""
    root = image_folder.strip("/")
    cfg = configured.strip("/")
    if not cfg:
        return root
    if cfg.startswith(root + "/") or cfg == root:
        return cfg
    return f"{root}/{cfg}"


def _library_list_prefix(paths: StoragePathConfig, logical: str) -> str:
    """S3 list prefix with trailing slash. ``logical`` is '', 'archive', 'keep', or 'remove'."""
    root = paths.image_folder.strip("/")
    if not logical:
        return f"{root}/"
    if logical == "archive":
        block = _resolved_folder_under_image_root(paths.image_folder, paths.archive_folder)
    elif logical == "keep":
        block = _resolved_folder_under_image_root(paths.image_folder, paths.folder_keep or "keep")
    elif logical == "remove":
        block = _resolved_folder_under_image_root(paths.image_folder, paths.folder_remove or "reject")
    else:
        return f"{root}/"
    return f"{block.strip('/')}/"


ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
VALID_TARGET_FOLDERS = {"keep", "remove", "archive", "root"}

# Pillow format names mapped to a trustworthy MIME we will store/serve.
_PILLOW_FORMAT_TO_MIME: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
}


_MAX_IMAGE_DIMENSION_PX = 12_000


def _verify_image_bytes(data: bytes | bytearray | memoryview) -> str:
    """Validate ``data`` via magic-byte parsing and return the trustworthy MIME.

    Raises HTTPException(415) when the bytes do not parse as an allowed image,
    matching the contract of ``ALLOWED_MIME_TYPES``.
    """
    # Imported lazily — Pillow is heavy and only needed on upload.
    from PIL import Image, UnidentifiedImageError

    # Make sure the global bomb ceiling from utils.images is applied even if
    # nothing imported that module yet in this process.
    import publisher_v2.utils.images  # noqa: F401

    try:
        # #136: read the buffer in place — no BytesIO copy of the upload.
        with Image.open(reader_over(data)) as img:
            img.verify()
            fmt = (img.format or "").upper()
        # verify() invalidates the parser — reopen for dimensions (#90).
        with Image.open(reader_over(data)) as img2:
            width, height = img2.size
    except Image.DecompressionBombError:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Image exceeds the allowed pixel count",
        ) from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Uploaded file is not a recognized image",
        ) from None

    if width > _MAX_IMAGE_DIMENSION_PX or height > _MAX_IMAGE_DIMENSION_PX:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Image dimensions {width}x{height} exceed {_MAX_IMAGE_DIMENSION_PX}px",
        )

    mime = _PILLOW_FORMAT_TO_MIME.get(fmt)
    if mime is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image format: {fmt or 'unknown'}",
        )
    return mime


# In-memory rate limit stores: {cookie_value: [timestamp, ...]}
_upload_rate_limit: dict[str, list[float]] = {}
_delete_rate_limit: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX = 10  # uploads per window
_DELETE_RATE_LIMIT_MAX = 20  # deletes per window (higher: deletes are lighter)


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
    total_in_window: int = 0
    truncated: bool = False
    anchor_offset: int | None = None


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
    if service.config.managed is None or not service.config.features.library_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not available for Dropbox instances",
        )


def _get_max_upload_bytes() -> int:
    """Max upload size in bytes (LIBRARY_MAX_UPLOAD_MB, default 20 MB; #97: centralized)."""
    return load_runtime_settings().library_max_upload_mb * 1024 * 1024


def _sanitize_filename(filename: str) -> str:
    """Sanitize upload filename: strip path traversal, normalize unicode, drop hostile chars."""
    name = PurePosixPath(filename).name
    name = unicodedata.normalize("NFC", name)
    # Drop control characters (incl. NUL) and bidi/format characters that
    # enable deceptive filename rendering (RTL override etc.).
    name = "".join(ch for ch in name if unicodedata.category(ch) not in {"Cc", "Cf"})
    # Strip path separators that survived basename extraction (defense in depth).
    name = name.replace("/", "").replace("\\", "")
    # Block pure-dot prefixes and parent traversal sequences.
    if name in {"", ".", ".."} or name.startswith(".."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")
    if name.startswith("."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")
    if len(name) > 255:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename too long")
    return name


def _prune_rate_dict(store: dict[str, list[float]], now: float) -> None:
    """#91 (SEC-10): drop cookie keys whose entries have all aged out."""
    stale = [key for key, stamps in store.items() if not stamps or now - stamps[-1] >= _RATE_LIMIT_WINDOW]
    for key in stale:
        store.pop(key, None)


def _check_rate_limit(request: Request) -> None:
    """Check upload rate limit (10/minute per admin session)."""
    cookie_val = request.cookies.get("pv2_admin", "anonymous")
    now = time.time()
    _prune_rate_dict(_upload_rate_limit, now)

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


def _check_delete_rate_limit(request: Request) -> None:
    """Check delete rate limit (20/minute per admin session)."""
    cookie_val = request.cookies.get("pv2_admin", "anonymous")
    now = time.time()
    _prune_rate_dict(_delete_rate_limit, now)

    if cookie_val not in _delete_rate_limit:
        _delete_rate_limit[cookie_val] = []

    _delete_rate_limit[cookie_val] = [t for t in _delete_rate_limit[cookie_val] if now - t < _RATE_LIMIT_WINDOW]

    if len(_delete_rate_limit[cookie_val]) >= _DELETE_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Delete rate limit exceeded (max 20/minute)",
        )

    _delete_rate_limit[cookie_val].append(now)


def _check_delete_enabled(service: WebImageService) -> None:
    """Raise 403 if delete feature is disabled."""
    if not service.config.features.delete_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delete feature is disabled",
        )


def _sanitize_filter(q: str | None) -> str | None:
    """Sanitize filter query: strip path traversal chars, null bytes, enforce max length."""
    if not q:
        return None
    cleaned = q.replace("/", "").replace("\\", "").replace("..", "").replace("\x00", "")
    cleaned = cleaned.strip()[:100]
    return cleaned or None


def _get_scan_budget() -> int:
    """Listing scan budget (LIBRARY_SCAN_BUDGET, default 5000; #97: centralized)."""
    return load_runtime_settings().library_scan_budget


_SORT_KEYS = {
    "name": lambda obj: obj["key"].lower(),
    "last_modified": lambda obj: obj["last_modified_raw"],
    "size": lambda obj: obj["size"],
}

_VALID_SORT_FIELDS = {"name", "last_modified", "size"}
_VALID_ORDER_VALUES = {"asc", "desc"}


async def _list_objects_buffered(
    service: WebImageService,
    prefix: str,
    q: str | None,
    sort: str,
    order: str,
    offset: int,
    limit: int,
    scan_budget: int,
    anchor_key: str | None = None,
) -> dict[str, Any]:
    """Scan up to scan_budget keys, filter, sort, paginate in memory.

    When *anchor_key* is provided the offset is overridden to the page
    containing that filename (same sort/filter), so the grid opens on the
    page that holds the anchor image.
    """
    storage: ObjectStorageProtocol = service.storage  # type: ignore[assignment]
    _image_suffixes = (".jpg", ".jpeg", ".png")
    sanitized_q = _sanitize_filter(q)

    # #96: the router talks ONLY to the storage protocol; page fetching,
    # bucket names and PUB-045 metering live inside ManagedStorage.
    items: list[dict[str, Any]] = []
    continuation: str | None = None
    truncated = False
    for _ in range(500):  # safety cap on pages
        if len(items) >= scan_budget:
            truncated = True
            break
        page = await storage.list_objects(prefix, cursor=continuation, limit=min(1000, scan_budget - len(items)))
        for obj in page["items"]:
            key: str = obj["key"]
            fname = key.rsplit("/", 1)[-1] if "/" in key else key
            if not fname.lower().endswith(_image_suffixes):
                continue
            items.append(
                {
                    "key": fname,
                    "size": obj.get("size", 0),
                    "last_modified_raw": obj.get("last_modified") or "",
                    "last_modified": str(obj.get("last_modified") or ""),
                }
            )
            if len(items) >= scan_budget:
                if page["is_truncated"]:
                    truncated = True
                break
        if not page["is_truncated"] or not page["cursor"]:
            break
        continuation = page["cursor"]

    # Apply filter
    if sanitized_q:
        q_lower = sanitized_q.lower()
        items = [it for it in items if q_lower in it["key"].lower()]

    # Sort
    sort_key = _SORT_KEYS[sort]
    items.sort(key=sort_key, reverse=(order == "desc"))

    total_in_window = len(items)

    # When anchor_key is given, find its position and override offset
    anchor_offset: int | None = None
    effective_offset = offset
    if anchor_key:
        for idx, it in enumerate(items):
            if it["key"] == anchor_key:
                effective_offset = (idx // limit) * limit
                anchor_offset = effective_offset
                break
        # anchor not found in window → keep caller-supplied offset

    # Paginate
    page_items = items[effective_offset : effective_offset + limit]

    # Build response objects (drop last_modified_raw)
    objects = [{"key": it["key"], "size": it["size"], "last_modified": it["last_modified"]} for it in page_items]

    return {
        "objects": objects,
        "cursor": None,
        "total_in_window": total_in_window,
        "truncated": truncated,
        "anchor_offset": anchor_offset,
    }


async def _list_objects_from_storage(
    service: WebImageService, prefix: str, cursor: str | None, limit: int
) -> dict[str, Any]:
    """List objects from managed storage with size/metadata.

    Uses S3 ``Delimiter='/'`` so only **immediate** child objects under ``prefix``
    are returned (same semantics as :meth:`ManagedStorage.list_images`). Without
    this, keys under ``{root}/archive/`` would also match ``{root}/`` and appear
    incorrectly as files in the library "root" view.
    """
    # Library endpoints only run for ManagedStorage (guarded by _check_library_available)
    storage: ObjectStorageProtocol = service.storage  # type: ignore[assignment]
    _image_suffixes = (".jpg", ".jpeg", ".png")

    objects: list[dict[str, Any]] = []
    continuation: str | None = cursor
    page_cap = min(max(limit, 1), 200)

    for _ in range(100):
        if len(objects) >= limit:
            break
        page = await storage.list_objects(prefix, cursor=continuation, limit=page_cap)
        for obj in page["items"]:
            key: str = obj["key"]
            fname = key.rsplit("/", 1)[-1] if "/" in key else key
            if not fname.lower().endswith(_image_suffixes):
                continue
            objects.append(
                {
                    "key": fname,
                    "size": obj.get("size", 0),
                    "last_modified": str(obj.get("last_modified") or ""),
                }
            )
            if len(objects) >= limit:
                next_cursor: str | None = page["cursor"] if page["is_truncated"] else None
                return {"objects": objects[:limit], "cursor": next_cursor}
        if not page["is_truncated"] or not page["cursor"]:
            return {"objects": objects, "cursor": None}
        continuation = page["cursor"]

    return {"objects": objects[:limit], "cursor": None}


def _invalidate_listing(service: WebImageService) -> None:
    """Drop the service's cached listing after a write (#144).

    Called directly rather than through getattr: a rename would then be a type
    error here instead of a silent no-op that brings back the 30-second window
    where a just-uploaded file cannot be moved.
    """
    service.invalidate_image_listing()


async def _upload_to_storage(
    service: WebImageService, filename: str, data: bytes | bytearray, content_type: str
) -> dict[str, Any]:
    """Upload file to managed storage (protocol-only, #96; metering inside)."""
    folder = service.config.storage_paths.image_folder
    key = f"{folder.strip('/')}/{filename}".lstrip("/")
    storage: ObjectStorageProtocol = service.storage  # type: ignore[assignment]
    await storage.put_object(key, data, content_type)
    _invalidate_listing(service)
    return {"key": key, "size": len(data)}


async def _delete_from_storage(service: WebImageService, filename: str) -> dict[str, Any]:
    """Delete image + sidecar from managed storage (protocol-only, #96)."""
    storage: ObjectStorageProtocol = service.storage  # type: ignore[assignment]
    folder = service.config.storage_paths.image_folder
    key = f"{folder.strip('/')}/{filename}".lstrip("/")

    if await storage.head_object(key) is None:
        raise FileNotFoundError(f"File not found: {filename}")
    await storage.delete_object(key)
    _invalidate_listing(service)

    stem = os.path.splitext(filename)[0]
    sidecar_key = f"{folder.strip('/')}/{stem}.txt".lstrip("/")
    sidecar_deleted = False
    if await storage.head_object(sidecar_key) is not None:
        with contextlib.suppress(Exception):
            await storage.delete_object(sidecar_key)
            sidecar_deleted = True
    return {"deleted": filename, "sidecar_deleted": sidecar_deleted}


async def _move_in_storage(service: WebImageService, filename: str, target_folder: str) -> dict[str, Any]:
    """Move image + sidecar to target folder in managed storage."""
    paths = service.config.storage_paths
    source_folder = paths.image_folder

    # Resolve target (INI may use short segments; orchestrator uses full key prefixes)
    if target_folder == "root":
        dest_folder = paths.image_folder
    elif target_folder == "archive":
        dest_folder = _resolved_folder_under_image_root(paths.image_folder, paths.archive_folder)
    elif target_folder == "keep":
        dest_folder = _resolved_folder_under_image_root(paths.image_folder, paths.folder_keep or "keep")
    elif target_folder == "remove":
        dest_folder = _resolved_folder_under_image_root(paths.image_folder, paths.folder_remove or "reject")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid target_folder: {target_folder}")

    src_key = f"{source_folder.strip('/')}/{filename}".lstrip("/")
    dst_key = f"{dest_folder.strip('/')}/{filename}".lstrip("/")

    storage: ObjectStorageProtocol = service.storage  # type: ignore[assignment]
    await storage.move_object(src_key, dst_key)
    _invalidate_listing(service)

    stem = os.path.splitext(filename)[0]
    sidecar_src = f"{source_folder.strip('/')}/{stem}.txt".lstrip("/")
    sidecar_dst = f"{dest_folder.strip('/')}/{stem}.txt".lstrip("/")
    with contextlib.suppress(Exception):
        await storage.move_object(sidecar_src, sidecar_dst)
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
    q: str | None = None,
    sort: str = "name",
    order: str = "asc",
    offset: int = 0,
    anchor_key: str | None = None,
    service: WebImageService = Depends(get_request_service),
) -> LibraryListResponse:
    """List objects under instance prefix (paginated).

    When *anchor_key* is provided the server locates the filename within the
    sorted/filtered result set and returns the page containing it (overriding
    *offset*).  The computed offset is returned as ``anchor_offset`` so the
    client can sync its pagination state.
    """
    await require_auth(request)
    require_admin(request)
    _check_library_available(service)

    # Validate sort/order
    if sort not in _VALID_SORT_FIELDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid sort field: {sort}")
    if order not in _VALID_ORDER_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid order: {order}")

    # Clamp limit
    limit = min(max(1, limit), 200)
    offset = max(0, offset)

    paths = service.config.storage_paths
    if prefix in ("archive", "keep", "remove"):
        storage_prefix = _library_list_prefix(paths, prefix)
    else:
        storage_prefix = _library_list_prefix(paths, "")

    # anchor_key forces the buffered path (needs full scan + sort to locate)
    use_buffered = (
        q is not None or sort != "name" or order != "asc" or offset > 0 or cursor is None or anchor_key is not None
    )
    use_legacy = not use_buffered and cursor is not None

    if use_legacy:
        result = await _list_objects_from_storage(service, storage_prefix, cursor, limit)
        result["total_in_window"] = 0
        result["truncated"] = False
    else:
        scan_budget = _get_scan_budget()
        result = await _list_objects_buffered(
            service, storage_prefix, q, sort, order, offset, limit, scan_budget, anchor_key=anchor_key
        )

    return LibraryListResponse(**result)


# Room for the multipart envelope (boundary lines, part headers) on top of the file cap.
_MULTIPART_OVERHEAD_BYTES = 16 * 1024
# #136: one part's headers may not exceed this (python-multipart does not bound them).
_MAX_PART_HEADER_BYTES = 8 * 1024
# #136: a whole upload must arrive within this many seconds (slow-body hold-open).
_UPLOAD_READ_TIMEOUT_SECONDS = 300.0


async def _read_single_file_part(request: Request, max_bytes: int) -> tuple[bytearray, str | None]:
    """Stream the multipart body and keep only the ``file`` part (#136).

    Chunks from ``request.stream()`` are fed to python-multipart's streaming
    parser as they arrive; only the file part's bytes are kept. Reading stops
    with 413 as soon as the file passes ``max_bytes`` or the raw body passes
    ``max_bytes`` plus the envelope allowance, so the rest of an oversized
    stream is never consumed and peak memory is the file plus one chunk.
    """
    from python_multipart.exceptions import MultipartParseError
    from python_multipart.multipart import MultipartParser, parse_options_header
    from starlette.requests import ClientDisconnect

    max_mb = max_bytes // (1024 * 1024)
    too_large = HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail=f"File too large (> {max_bytes} bytes). Maximum: {max_mb} MB",
    )
    ctype, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if ctype.lower() != b"multipart/form-data" or not boundary:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expected multipart/form-data")

    file_buf = bytearray()
    header_too_large = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Multipart part headers too large")
    field, value = bytearray(), bytearray()
    state: dict[str, Any] = {"headers": {}, "header_bytes": 0, "capture": False, "filename": None}
    seen_file = False

    def _count_header(n: int) -> None:
        state["header_bytes"] += n
        if state["header_bytes"] > _MAX_PART_HEADER_BYTES:
            raise header_too_large

    def on_part_begin() -> None:
        state["headers"] = {}
        state["header_bytes"] = 0
        state["capture"] = False

    def on_header_field(data: bytes, start: int, end: int) -> None:
        _count_header(end - start)
        field.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        _count_header(end - start)
        value.extend(data[start:end])

    def on_header_end() -> None:
        state["headers"][bytes(field).lower()] = bytes(value)
        field.clear()
        value.clear()

    def on_headers_finished() -> None:
        nonlocal seen_file
        _disp, disp_params = parse_options_header(state["headers"].get(b"content-disposition", b""))
        if disp_params.get(b"name") == b"file" and not seen_file:
            seen_file = True
            state["capture"] = True
            raw_name = disp_params.get(b"filename")
            state["filename"] = raw_name.decode("utf-8", "replace") if raw_name is not None else None

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if state["capture"]:
            file_buf.extend(data[start:end])
            if len(file_buf) > max_bytes:
                raise too_large

    def on_part_end() -> None:
        state["capture"] = False

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
    )
    body_limit = max_bytes + _MULTIPART_OVERHEAD_BYTES
    received = 0
    try:
        async with asyncio.timeout(_UPLOAD_READ_TIMEOUT_SECONDS):
            async for chunk in request.stream():
                received += len(chunk)
                if received > body_limit:
                    raise too_large
                parser.write(chunk)
                # Everything that is not file data (part headers, other fields,
                # whitespace, junk parts) shares the envelope allowance, so no
                # body can spend the whole cap on per-byte parsing work.
                if received - len(file_buf) > _MULTIPART_OVERHEAD_BYTES + len(chunk):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Multipart envelope too large")
        parser.finalize()
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_408_REQUEST_TIMEOUT, detail="Upload took too long") from None
    except MultipartParseError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed multipart body") from None
    except ClientDisconnect:
        # The client went away mid-upload (e.g. cancelled): nothing to store, no 500.
        log_json(logger, logging.INFO, "library_upload_client_disconnect", received=received)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload interrupted") from None
    if not seen_file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing 'file' part")
    return file_buf, state["filename"]


@router.post("/upload", response_model=LibraryUploadResponse)
async def upload_file(
    request: Request,
    service: WebImageService = Depends(get_request_service),
) -> LibraryUploadResponse:
    """Upload image to managed storage.

    #136: the route takes no ``UploadFile`` — FastAPI would otherwise parse (and
    spool) the whole multipart body before any of the checks below ran. Auth,
    admin, rate limit and the declared Content-Length are all checked before the
    first body byte is read.
    """
    await require_auth(request)
    require_admin(request)
    _check_library_available(service)

    # #90 (SEC-6): rate limit BEFORE reading any body bytes.
    _check_rate_limit(request)

    max_bytes = _get_max_upload_bytes()
    max_mb = max_bytes // (1024 * 1024)

    # Reject on the declared Content-Length before touching the body.
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > max_bytes + _MULTIPART_OVERHEAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File too large (Content-Length {declared}). Maximum: {max_mb} MB",
                )
        except ValueError:
            pass

    data, raw_filename = await _read_single_file_part(request, max_bytes)

    # Validate content via magic bytes (do NOT trust client-supplied
    # Content-Type). Pillow parsing is CPU-bound — off the event loop (#90).
    # The bytearray is passed as-is: no second copy of the upload (#136).
    content_type = await asyncio.to_thread(_verify_image_bytes, data)

    # Sanitize filename
    filename = _sanitize_filename(raw_filename or "upload.jpg")

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
    _check_delete_enabled(service)
    _check_delete_rate_limit(request)

    try:
        result = await _delete_from_storage(service, _sanitize_filename(filename))
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

    # #144: the raw path parameter used to be interpolated straight into the
    # source and destination keys. Sanitize it, and require it to be in the
    # listing — a move writes a new key as well as removing one, so a name that
    # sanitizes cleanly but does not exist would create an empty destination.
    # Note this is STRICTER than delete, which sanitizes without a listing
    # check; see #128 for whether delete should match.
    safe_name = _sanitize_filename(filename)
    try:
        await service.ensure_known_image(safe_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {safe_name}") from exc

    result = await _move_in_storage(service, safe_name, body.target_folder)
    log_json(logger, logging.INFO, "library_move", filename=safe_name, destination=body.target_folder)
    return LibraryMoveResponse(**result)
