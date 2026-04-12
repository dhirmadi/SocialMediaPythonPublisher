"""Tests for PUB-031 Phase A: Migration CLI (AC1–AC8)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_dropbox_storage(files: dict[str, bytes] | None = None, sidecars: dict[str, bytes] | None = None):
    """Create a mock DropboxStorage with controllable file/sidecar content."""
    files = files or {}
    sidecars = sidecars or {}

    storage = AsyncMock()

    async def _list_images(folder: str) -> list[str]:
        prefix = folder.rstrip("/") + "/"
        result = []
        for k in files:
            if not k.startswith(prefix):
                continue
            if not k.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            # Only return files directly in this folder, not in subfolders
            relative = k[len(prefix) :]
            if "/" not in relative:
                result.append(relative)
        return result

    async def _list_images_with_hashes(folder: str) -> list[tuple[str, str]]:
        prefix = folder.rstrip("/") + "/"
        result = []
        for k in files:
            if not k.startswith(prefix):
                continue
            if not k.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            relative = k[len(prefix) :]
            if "/" not in relative:
                result.append((relative, f"dbx_hash_{relative}"))
        return result

    async def _download_image(folder: str, filename: str) -> bytes:
        key = f"{folder.rstrip('/')}/{filename}"
        if key not in files:
            raise FileNotFoundError(f"Not found: {key}")
        return files[key]

    async def _download_sidecar_if_exists(folder: str, filename: str) -> bytes | None:
        import os

        stem = os.path.splitext(filename)[0]
        sidecar_key = f"{folder.rstrip('/')}/{stem}.txt"
        return sidecars.get(sidecar_key)

    storage.list_images = AsyncMock(side_effect=_list_images)
    storage.list_images_with_hashes = AsyncMock(side_effect=_list_images_with_hashes)
    storage.download_image = AsyncMock(side_effect=_download_image)
    storage.download_sidecar_if_exists = AsyncMock(side_effect=_download_sidecar_if_exists)

    return storage


def _make_mock_managed_storage(existing_keys: dict[str, str] | None = None):
    """Create a mock ManagedStorage. existing_keys maps S3 key -> ETag."""
    existing_keys = existing_keys or {}
    uploaded: dict[str, bytes] = {}

    storage = AsyncMock()

    async def _head_object(key: str) -> dict[str, str] | None:
        if key in existing_keys:
            return {"ETag": existing_keys[key]}
        return None

    async def _put_object(key: str, body: bytes, content_type: str = "") -> None:
        uploaded[key] = body

    storage.head_object = AsyncMock(side_effect=_head_object)
    storage.put_object = AsyncMock(side_effect=_put_object)
    storage.uploaded = uploaded

    return storage


# ---------------------------------------------------------------------------
# AC1: CLI arg parsing and required env vars
# ---------------------------------------------------------------------------


class TestCLIArgParsing:
    """AC1: Migration tool validates required env vars and CLI args."""

    def test_missing_env_vars_exit_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing required env vars → exit code 1 with clear error."""
        # Clear all migration-related env vars
        for var in [
            "DROPBOX_APP_KEY",
            "DROPBOX_APP_SECRET",
            "MIGRATE_DROPBOX_REFRESH_TOKEN",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_ENDPOINT_URL",
            "R2_BUCKET_NAME",
        ]:
            monkeypatch.delenv(var, raising=False)

        from publisher_v2.tools.migrate_storage import validate_env_vars

        errors = validate_env_vars()
        assert len(errors) > 0
        # Should list all missing vars
        assert any("DROPBOX_APP_KEY" in e for e in errors)
        assert any("R2_ENDPOINT_URL" in e for e in errors)

    def test_all_env_vars_present_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All required env vars present → no errors."""
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("MIGRATE_DROPBOX_REFRESH_TOKEN", "test_token")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "AKID")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "SECRET")
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://r2.example.com")
        monkeypatch.setenv("R2_BUCKET_NAME", "bucket")

        from publisher_v2.tools.migrate_storage import validate_env_vars

        errors = validate_env_vars()
        assert errors == []

    def test_cli_arg_parsing(self) -> None:
        """CLI args are parsed correctly."""
        from publisher_v2.tools.migrate_storage import parse_args

        args = parse_args(
            [
                "--source-folder",
                "/My Photos",
                "--target-prefix",
                "tenant/instance",
                "--dry-run",
                "--limit",
                "5",
            ]
        )
        assert args.source_folder == "/My Photos"
        assert args.target_prefix == "tenant/instance"
        assert args.dry_run is True
        assert args.limit == 5
        assert args.resume is True  # default

    def test_cli_arg_archive_folder(self) -> None:
        """--archive-folder is optional."""
        from publisher_v2.tools.migrate_storage import parse_args

        args = parse_args(
            [
                "--source-folder",
                "/Photos",
                "--target-prefix",
                "t/i",
                "--archive-folder",
                "/Photos/archive",
            ]
        )
        assert args.archive_folder == "/Photos/archive"


# ---------------------------------------------------------------------------
# AC2: Dry-run mode
# ---------------------------------------------------------------------------


class TestDryRun:
    """AC2: --dry-run lists files without writing to R2."""

    async def test_dry_run_lists_without_writing(self) -> None:
        source = _make_mock_dropbox_storage(
            files={
                "/Photos/img1.jpg": b"image1",
                "/Photos/img2.png": b"image2",
            }
        )
        target = _make_mock_managed_storage()

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="tenant/instance",
            subfolders=[],
            dry_run=True,
            limit=None,
        )

        assert result.total_files == 2
        # No uploads should have been made
        target.put_object.assert_not_called()

    async def test_dry_run_summary_counts(self) -> None:
        source = _make_mock_dropbox_storage(
            files={
                "/Photos/a.jpg": b"aaa",
                "/Photos/b.jpg": b"bbb",
                "/Photos/c.png": b"ccc",
            }
        )
        target = _make_mock_managed_storage()

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=True,
            limit=None,
        )

        assert result.total_files == 3
        assert result.total_bytes == len(b"aaa") + len(b"bbb") + len(b"ccc")


# ---------------------------------------------------------------------------
# AC3: Normal copy with sidecars
# ---------------------------------------------------------------------------


class TestNormalCopy:
    """AC3: Copies images and sidecars from Dropbox to R2."""

    async def test_copies_image_and_sidecar(self) -> None:
        source = _make_mock_dropbox_storage(
            files={"/Photos/img1.jpg": b"image-data"},
            sidecars={"/Photos/img1.txt": b"sidecar-data"},
        )
        target = _make_mock_managed_storage()

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=False,
            limit=None,
        )

        assert result.copied == 1
        assert result.errors == 0
        # Should have uploaded both image and sidecar
        assert target.put_object.call_count == 2

    async def test_skips_sidecar_when_absent(self) -> None:
        source = _make_mock_dropbox_storage(
            files={"/Photos/img1.jpg": b"image-data"},
            sidecars={},  # No sidecar
        )
        target = _make_mock_managed_storage()

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=False,
            limit=None,
        )

        assert result.copied == 1
        # Only image uploaded, no sidecar
        assert target.put_object.call_count == 1


# ---------------------------------------------------------------------------
# AC4: Subfolder structure preserved
# ---------------------------------------------------------------------------


class TestSubfolderStructure:
    """AC4: archive/, keep/, remove/ subfolders are preserved."""

    async def test_preserves_subfolder_structure_archive_keep_remove(self) -> None:
        source = _make_mock_dropbox_storage(
            files={
                "/Photos/img1.jpg": b"root-image",
                "/Photos/archive/img2.jpg": b"archive-image",
                "/Photos/keep/img3.jpg": b"keep-image",
                "/Photos/remove/img4.jpg": b"remove-image",
            }
        )
        target = _make_mock_managed_storage()

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=["archive", "keep", "remove"],
            dry_run=False,
            limit=None,
        )

        assert result.copied == 4
        assert result.errors == 0

        # Verify the keys used for uploads include subfolder structure
        call_keys = [call.args[0] for call in target.put_object.call_args_list]
        assert "t/i/img1.jpg" in call_keys
        assert "t/i/archive/img2.jpg" in call_keys
        assert "t/i/keep/img3.jpg" in call_keys
        assert "t/i/remove/img4.jpg" in call_keys


# ---------------------------------------------------------------------------
# AC5: Idempotency (resume)
# ---------------------------------------------------------------------------


class TestIdempotency:
    """AC5: Re-running skips existing files; re-copies on hash mismatch."""

    async def test_idempotent_skip_existing(self) -> None:
        source = _make_mock_dropbox_storage(
            files={"/Photos/img1.jpg": b"image-data"},
        )
        # Target already has the file
        target = _make_mock_managed_storage(existing_keys={"t/i/img1.jpg": "dbx_hash_img1.jpg"})

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=False,
            limit=None,
        )

        assert result.skipped == 1
        assert result.copied == 0
        target.put_object.assert_not_called()

    async def test_recopy_on_hash_mismatch(self) -> None:
        source = _make_mock_dropbox_storage(
            files={"/Photos/img1.jpg": b"image-data"},
        )
        # Target has the file but with a different ETag
        target = _make_mock_managed_storage(existing_keys={"t/i/img1.jpg": "DIFFERENT_HASH"})

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=False,
            limit=None,
        )

        assert result.copied == 1
        assert result.skipped == 0


# ---------------------------------------------------------------------------
# AC6: --limit N
# ---------------------------------------------------------------------------


class TestLimit:
    """AC6: --limit N caps the number of images copied."""

    async def test_limit_caps_copied_count(self) -> None:
        source = _make_mock_dropbox_storage(
            files={
                "/Photos/img1.jpg": b"data1",
                "/Photos/img2.jpg": b"data2",
                "/Photos/img3.jpg": b"data3",
            }
        )
        target = _make_mock_managed_storage()

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=False,
            limit=2,
        )

        assert result.copied == 2
        assert result.total_files <= 3  # May list all but only copy 2


# ---------------------------------------------------------------------------
# AC7: Per-file error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """AC7: Per-file errors logged, tool continues, exit code reflects."""

    async def test_per_file_error_continues_and_summary(self) -> None:
        source = _make_mock_dropbox_storage(
            files={
                "/Photos/good.jpg": b"good-data",
                "/Photos/bad.jpg": b"bad-data",
            }
        )
        target = _make_mock_managed_storage()

        # Make upload fail for bad.jpg
        original_put = target.put_object.side_effect

        async def _put_with_error(key: str, body: bytes, content_type: str = "") -> None:
            if "bad.jpg" in key:
                raise Exception("Upload failed for bad.jpg")
            if original_put:
                await original_put(key, body, content_type)

        target.put_object = AsyncMock(side_effect=_put_with_error)

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=False,
            limit=None,
        )

        assert result.copied == 1
        assert result.errors == 1

    async def test_exit_code_1_on_errors(self) -> None:
        """Migration result with errors should signal exit code 1."""
        from publisher_v2.tools.migrate_storage import MigrationResult

        result = MigrationResult(copied=1, skipped=0, errors=1, total_files=2, total_bytes=100)
        assert result.exit_code == 1

    async def test_exit_code_0_no_errors(self) -> None:
        from publisher_v2.tools.migrate_storage import MigrationResult

        result = MigrationResult(copied=2, skipped=0, errors=0, total_files=2, total_bytes=100)
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# AC8: No secrets in log output
# ---------------------------------------------------------------------------


class TestNoSecretsInLogs:
    """AC8: Sensitive env var values must not appear in log output."""

    async def test_no_secrets_in_log_output(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Run a dry-run migration and verify no secrets in captured logs."""
        secret_token = "sl.B0abcdefghij1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

        monkeypatch.setenv("MIGRATE_DROPBOX_REFRESH_TOKEN", secret_token)
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", secret_key)

        source = _make_mock_dropbox_storage(
            files={"/Photos/img1.jpg": b"data"},
        )
        target = _make_mock_managed_storage()

        from publisher_v2.tools.migrate_storage import run_migration

        with caplog.at_level(logging.DEBUG):
            await run_migration(
                source=source,
                target=target,
                source_folder="/Photos",
                target_prefix="t/i",
                subfolders=[],
                dry_run=True,
                limit=None,
            )

        full_log = caplog.text
        assert secret_token not in full_log
        assert secret_key not in full_log
