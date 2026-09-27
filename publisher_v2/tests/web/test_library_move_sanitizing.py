"""#144 item 5: the move endpoint passed the raw path parameter to storage.

delete_object sanitizes its filename; move_object did not, so a traversal-ish
name was interpolated straight into the source and destination keys, and any
name at all was accepted whether or not it was in the listing.

Runs through the real ``publisher_v2.web.app.app``, the real env-first config
loader and the real ``ManagedStorage``; the fake sits at the boto3 client
boundary and records what the tool would have asked S3 to do.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from .conftest import MANAGED_KEY_PREFIX as KEY_PREFIX
from .conftest import FakeS3


@pytest.fixture
def client_and_s3(
    managed_real_app: Callable[..., FakeS3], admin_asgi_client: Callable[..., httpx.AsyncClient]
) -> tuple[httpx.AsyncClient, FakeS3]:
    """One image in the root listing, one in the keep folder (outside the root listing)."""
    s3 = managed_real_app(objects=[f"{KEY_PREFIX}/known.jpg", f"{KEY_PREFIX}/keep/kept.jpg"])
    return admin_asgi_client(), s3


async def _move(client: httpx.AsyncClient, filename: str) -> httpx.Response:
    return await client.post(f"/api/library/objects/{filename}/move", json={"target_folder": "archive"})


@pytest.mark.parametrize(
    ("hostile", "expected_status"),
    [
        # 400 is the sanitizer's own rejection. Asserting the exact code is the
        # point: with ``in (400, 404)`` these two cases pass even when
        # ``_sanitize_filename`` is removed from the handler, because the
        # listing check then 404s them instead — so the test could not detect
        # the loss of the half of the fix it is named after.
        ("..%5Cx.jpg", 400),  # backslash survives routing; the sanitizer must strip it
        ("%2e%2e.jpg", 400),  # decodes to "..jpg" — a name, not a traversal, but never listed
        # Rejected by Starlette's routing before the handler runs at all, so no
        # sanitizer involved and nothing for it to pin.
        ("..%2Fx.jpg", 404),
    ],
)
async def test_traversal_name_never_reaches_storage(
    client_and_s3: tuple[httpx.AsyncClient, FakeS3], hostile: str, expected_status: int
) -> None:
    client, s3 = client_and_s3

    response = await _move(client, hostile)

    assert response.status_code == expected_status, response.text
    assert s3.copied == []
    assert s3.deleted == []


async def test_unlisted_name_is_404(client_and_s3: tuple[httpx.AsyncClient, FakeS3]) -> None:
    client, s3 = client_and_s3

    response = await _move(client, "not-in-the-listing.jpg")

    assert response.status_code == 404, response.text
    assert s3.copied == []


async def test_an_object_uploaded_moments_ago_can_be_moved(
    client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """#144: ensure_known_image reads a 30s listing cache — a write must invalidate it."""
    client, s3 = client_and_s3
    # Warm the listing cache, as any page load would.
    await _move(client, "known.jpg")
    s3.copied.clear()
    s3.add(f"{KEY_PREFIX}/fresh.jpg")

    response = await _move(client, "fresh.jpg")

    assert response.status_code == 200, response.text
    assert (f"{KEY_PREFIX}/fresh.jpg", f"{KEY_PREFIX}/archive/fresh.jpg") in s3.copied


async def test_listed_name_still_moves(client_and_s3: tuple[httpx.AsyncClient, FakeS3]) -> None:
    client, s3 = client_and_s3

    response = await _move(client, "known.jpg")

    assert response.status_code == 200, response.text
    assert (f"{KEY_PREFIX}/known.jpg", f"{KEY_PREFIX}/archive/known.jpg") in s3.copied


# --- PUB-048 (#188) AC6/AC7: same-key moves and a real source folder ---


async def test_move_target_root_when_already_in_root_rejects_same_key(
    client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """AC6: root -> root is a copy onto itself, which R2/MinIO honour and then delete."""
    client, s3 = client_and_s3

    response = await client.post("/api/library/objects/known.jpg/move", json={"target_folder": "root"})

    assert response.status_code == 400, response.text
    assert s3.copied == []
    assert s3.deleted == []


async def test_move_from_keep_folder_to_root_uses_keep_folder_as_source_key(
    client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """AC7: source_folder=keep must resolve the source prefix, not assume the image root."""
    client, s3 = client_and_s3

    response = await client.post(
        "/api/library/objects/kept.jpg/move",
        json={"target_folder": "root", "source_folder": "keep"},
    )

    assert response.status_code == 200, response.text
    assert (f"{KEY_PREFIX}/keep/kept.jpg", f"{KEY_PREFIX}/kept.jpg") in s3.copied
    assert f"{KEY_PREFIX}/keep/kept.jpg" in s3.deleted
    # The destination must never be the key that gets deleted (the AC6 hazard).
    assert f"{KEY_PREFIX}/kept.jpg" not in s3.deleted


async def test_move_sidecar_txt_name_from_non_root_source_folder_returns_404(
    client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """AC7 negative: ensure_known_object must suffix-gate, not merely check existence.

    The field assertion pins the contract this 404 has to come from: without
    ``source_folder`` the body field is silently dropped as an extra key and the
    404 would only prove the old root-listing check, not the new helper's gate.
    """
    from publisher_v2.web.routers.library import LibraryMoveRequest

    assert "source_folder" in LibraryMoveRequest.model_fields
    client, s3 = client_and_s3

    response = await client.post(
        "/api/library/objects/notes.txt/move",
        json={"target_folder": "root", "source_folder": "keep"},
    )

    assert response.status_code == 404, response.text
    assert s3.copied == []
    assert s3.deleted == []


# --- PUB-048 AC11: a move must never clobber an existing destination ---


async def test_move_onto_existing_destination_name_returns_409_and_nothing_copied_or_deleted(
    client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """AC11: keep/a.jpg -> root when root already holds a.jpg must 409 before any write.

    ``ManagedStorage.move_object`` copies then deletes unconditionally, so an
    unguarded move would overwrite the root object and its sidecar and then
    remove the source. The recorded call lists are the assertion that matters:
    a 409 raised *after* the copy would still destroy data.
    """
    client, s3 = client_and_s3
    s3.add(f"{KEY_PREFIX}/a.jpg")  # already in the root folder (and its listing)
    s3.add(f"{KEY_PREFIX}/keep/a.jpg")

    response = await client.post(
        "/api/library/objects/a.jpg/move",
        json={"target_folder": "root", "source_folder": "keep"},
    )

    assert response.status_code == 409, response.text
    assert s3.copied == []
    assert s3.deleted == []


async def test_move_missing_object_from_non_root_source_folder_returns_404_and_nothing_copied_or_deleted(
    client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """AC7 existence branch: a correctly-suffixed name absent from the source folder 404s.

    This is the branch the per-key ``head_object`` fake unlocks
    (``WebImageService.ensure_known_object``'s ``head_object(...) is None ->
    FileNotFoundError``). The suffix gate cannot account for the 404 here:
    ``.jpg`` passes it, so only the existence check can reject.
    """
    client, s3 = client_and_s3
    assert f"{KEY_PREFIX}/keep/ghost.jpg" not in s3.objects

    response = await client.post(
        "/api/library/objects/ghost.jpg/move",
        json={"target_folder": "root", "source_folder": "keep"},
    )

    assert response.status_code == 404, response.text
    assert s3.copied == []
    assert s3.deleted == []
