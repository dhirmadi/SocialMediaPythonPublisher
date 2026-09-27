"""PUB-048 (#188) AC10: delete must operate only on image keys the listing knows.

``_delete_from_storage`` checks existence with a bare ``head_object`` and no
suffix restriction, so a raw sidecar key — or any object under the image folder
that the listing never returned — can be deleted directly.

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
def delete_client_and_s3(
    managed_real_app: Callable[..., FakeS3], admin_asgi_client: Callable[..., httpx.AsyncClient]
) -> tuple[httpx.AsyncClient, FakeS3]:
    """The bucket holds one listed image and its sidecar."""
    s3 = managed_real_app(
        env={"FEATURE_DELETE": "true"}, objects=[f"{KEY_PREFIX}/known.jpg", f"{KEY_PREFIX}/known.txt"]
    )
    return admin_asgi_client(), s3


async def test_delete_sidecar_name_returns_404_and_nothing_deleted(
    delete_client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """A sidecar sitting next to a listed image: the object exists, so only the gate can refuse it."""
    client, s3 = delete_client_and_s3
    assert s3.head_object(Bucket="bucket", Key=f"{KEY_PREFIX}/known.txt")  # present in the bucket

    response = await client.delete("/api/library/objects/known.txt")

    assert response.status_code == 404, response.text
    assert s3.deleted == []


async def test_delete_unlisted_image_name_returns_404_and_nothing_deleted(
    delete_client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """Correct suffix, present in the bucket, never in this worker's listing: the listing decides.

    The object is written behind the app's back after the listing is cached (another
    worker's upload), so ``head_object`` would say "present" — only the AC10 listing
    check can produce this 404.
    """
    client, s3 = delete_client_and_s3
    warm = await client.get("/api/images/known.jpg")  # caches the listing, as any page load does
    assert warm.status_code == 200, warm.text
    s3.add(f"{KEY_PREFIX}/ghost.jpg")
    assert s3.head_object(Bucket="bucket", Key=f"{KEY_PREFIX}/ghost.jpg")

    response = await client.delete("/api/library/objects/ghost.jpg")

    assert response.status_code == 404, response.text
    assert s3.deleted == []


async def test_delete_listed_image_still_works(
    delete_client_and_s3: tuple[httpx.AsyncClient, FakeS3],
) -> None:
    """Guard for the AC10 fix: the listed, correctly-suffixed name must still delete."""
    client, s3 = delete_client_and_s3

    response = await client.delete("/api/library/objects/known.jpg")

    assert response.status_code == 200, response.text
    assert f"{KEY_PREFIX}/known.jpg" in s3.deleted
