"""PUB-084 AC8 (#298): the shared web-test harness in ``tests/web/conftest.py``.

The S3 fake stands in for the boto3 client under the real ``ManagedStorage``. Its
``head_object`` must answer per key: PUB-048 AC9/AC11 made upload and move consult
existence before writing, so a fake that reports every key as present turns a
first upload into an overwrite and makes the existence branches untestable.
"""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError


def _is_404(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound")


def test_fake_s3_head_object_is_per_key(fake_s3) -> None:  # type: ignore[no-untyped-def]
    """AC8: presence follows what the fake holds — seeded, put, copied, deleted — never a blanket yes."""
    fake_s3.add("tenant/instance/seeded.jpg", b"seeded")

    assert fake_s3.head_object(Bucket="bucket", Key="tenant/instance/seeded.jpg")["ContentLength"] == len(b"seeded")
    with pytest.raises(ClientError) as absent:
        fake_s3.head_object(Bucket="bucket", Key="tenant/instance/never-written.jpg")
    assert _is_404(absent.value)

    fake_s3.put_object(Bucket="bucket", Key="tenant/instance/new.jpg", Body=b"new-bytes", ContentType="image/jpeg")
    assert fake_s3.head_object(Bucket="bucket", Key="tenant/instance/new.jpg")["ContentLength"] == len(b"new-bytes")

    fake_s3.copy_object(
        Bucket="bucket",
        Key="tenant/instance/archive/new.jpg",
        CopySource={"Bucket": "bucket", "Key": "tenant/instance/new.jpg"},
    )
    assert fake_s3.head_object(Bucket="bucket", Key="tenant/instance/archive/new.jpg")["ContentLength"] == len(
        b"new-bytes"
    )

    fake_s3.delete_object(Bucket="bucket", Key="tenant/instance/new.jpg")
    with pytest.raises(ClientError) as deleted:
        fake_s3.head_object(Bucket="bucket", Key="tenant/instance/new.jpg")
    assert _is_404(deleted.value)
    # A sibling key sharing a prefix is a different object.
    with pytest.raises(ClientError):
        fake_s3.head_object(Bucket="bucket", Key="tenant/instance/seeded.jpg.txt")
