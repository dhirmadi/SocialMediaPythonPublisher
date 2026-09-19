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

    async def _head_object(key: str) -> dict[str, object] | None:
        # #142: the shape ManagedStorage.head_object actually returns — the
        # migration reads the protocol method now, not a bespoke override.
        if key in existing_keys:
            return {"etag": existing_keys[key], "size": 1, "last_modified": None}
        return None

    async def _put_object(key: str, body: bytes, content_type: str = "") -> None:
        uploaded[key] = body

    async def _exists(key: str) -> bool:
        return key in existing_keys

    storage.head_object = AsyncMock(side_effect=_head_object)
    storage.exists = AsyncMock(side_effect=_exists)
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

    async def test_present_target_is_skipped_regardless_of_its_etag(self) -> None:
        """#142: content equality cannot be decided across backends.

        This replaces ``test_recopy_on_hash_mismatch``, which asserted that a
        differing ETag re-copies. R2's ETag (MD5-based) and Dropbox's
        ``content_hash`` (block SHA256) are never equal, so in production that
        branch fired for *every* file and the tool re-copied the whole library
        on every run. Resume is presence-based now; ``--no-resume`` is how an
        operator forces a re-copy (covered below).
        """
        source = _make_mock_dropbox_storage(
            files={"/Photos/img1.jpg": b"image-data"},
        )
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

        assert result.skipped == 1
        assert result.copied == 0


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


# --- #142: resume uses the protocol, and the target is a plain ManagedStorage ---


class TestResumeUsesTheProtocol:
    """The old ETag-vs-Dropbox-content_hash comparison could never match.

    R2 returns an MD5-based ETag; Dropbox returns a block-SHA256 content hash.
    The skip branch was therefore dead in production and every re-run re-copied
    everything. #142's ``exists(key)`` is the semantic the tool actually wants.
    """

    async def test_existing_target_key_is_skipped_without_re_uploading(self) -> None:
        source = _make_mock_dropbox_storage(files={"/Photos/img1.jpg": b"image-data"})
        target = _make_mock_managed_storage(existing_keys={"t/i/img1.jpg": "r2-etag-unrelated-to-dropbox"})

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

    async def test_no_resume_copies_even_when_the_target_exists(self) -> None:
        source = _make_mock_dropbox_storage(files={"/Photos/img1.jpg": b"image-data"})
        target = _make_mock_managed_storage(existing_keys={"t/i/img1.jpg": "whatever"})

        from publisher_v2.tools.migrate_storage import run_migration

        result = await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=False,
            limit=None,
            resume=False,
        )

        assert result.copied == 1
        assert result.skipped == 0

    async def test_resume_copies_a_sidecar_orphaned_by_an_interrupted_run(self) -> None:
        """Image present, sidecar missing: the earlier run died between the two puts."""
        source = _make_mock_dropbox_storage(
            files={"/Photos/img1.jpg": b"image-data"},
            sidecars={"/Photos/img1.txt": b"a caption"},
        )
        target = _make_mock_managed_storage(existing_keys={"t/i/img1.jpg": "etag"})

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
        assert target.uploaded == {"t/i/img1.txt": b"a caption"}

    async def test_resume_does_not_rewrite_a_sidecar_that_is_already_there(self) -> None:
        source = _make_mock_dropbox_storage(
            files={"/Photos/img1.jpg": b"image-data"},
            sidecars={"/Photos/img1.txt": b"a caption"},
        )
        target = _make_mock_managed_storage(existing_keys={"t/i/img1.jpg": "etag", "t/i/img1.txt": "etag2"})

        from publisher_v2.tools.migrate_storage import run_migration

        await run_migration(
            source=source,
            target=target,
            source_folder="/Photos",
            target_prefix="t/i",
            subfolders=[],
            dry_run=False,
            limit=None,
        )

        assert target.uploaded == {}


class TestTargetStorageIsTheRealBackend:
    """#142: the tool must use ManagedStorage itself, not a subclass of it."""

    def test_build_target_storage_returns_a_plain_managed_storage(self, monkeypatch) -> None:
        from unittest.mock import MagicMock, patch

        from publisher_v2.services.managed_storage import ManagedStorage
        from publisher_v2.services.storage_protocol import ObjectStorageProtocol
        from publisher_v2.tools.migrate_storage import _build_target_storage

        for key, value in {
            "R2_ACCESS_KEY_ID": "k",
            "R2_SECRET_ACCESS_KEY": "s",
            "R2_ENDPOINT_URL": "https://example.r2.local",
            "R2_BUCKET_NAME": "bucket",
        }.items():
            monkeypatch.setenv(key, value)

        with patch("publisher_v2.services.managed_storage.boto3") as boto:
            boto.client = MagicMock(return_value=MagicMock())
            target = _build_target_storage()

        assert type(target) is ManagedStorage
        assert isinstance(target, ObjectStorageProtocol)


class TestCliWiring:
    """#142: --no-resume was parsed and silently dropped before reaching run_migration."""

    async def test_no_resume_flag_reaches_run_migration(self, monkeypatch) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from publisher_v2.tools import migrate_storage as mod

        captured: dict[str, object] = {}

        async def _fake_run(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(exit_code=0)

        monkeypatch.setattr(mod, "validate_env_vars", lambda: [])
        monkeypatch.setattr(mod, "_build_source_storage", lambda args: MagicMock())
        monkeypatch.setattr(mod, "_build_target_storage", lambda: MagicMock())
        monkeypatch.setattr(mod, "run_migration", AsyncMock(side_effect=_fake_run))
        monkeypatch.setattr(
            "sys.argv",
            ["migrate_storage", "--source-folder", "/Photos", "--target-prefix", "t/i", "--no-resume"],
        )

        assert await mod.async_main() == 0
        assert captured["resume"] is False
