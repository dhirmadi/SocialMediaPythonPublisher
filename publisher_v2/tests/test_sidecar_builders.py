from __future__ import annotations

from publisher_v2.services.storage_protocol import FileMetadata
from publisher_v2.utils.captions import (
    build_caption_sidecar,
    build_metadata_phase1,
)


def test_build_metadata_phase1_omits_missing() -> None:
    meta = build_metadata_phase1(
        image_file="IMG_001.jpg",
        sha256="abc",
        created_iso="2025-02-18T11:32:01Z",
        sd_caption_version="v1.0",
        model_version="gpt-4o",
        dropbox_file_id=None,
        dropbox_rev=None,
    )
    assert "image_file" in meta
    assert "sha256" in meta
    assert "created" in meta
    assert "sd_caption_version" in meta
    assert "model_version" in meta
    assert "dropbox_file_id" not in meta
    assert "dropbox_rev" not in meta


def test_build_caption_sidecar_formatting() -> None:
    meta = {
        "image_file": "IMG_001.jpg",
        "sha256": "abc",
        "created": "2025-02-18T11:32:01Z",
        "tags": ["a", "b"],
    }
    sd = "a fine-art figure study, standing pose, low-key lighting"
    content = build_caption_sidecar(sd, meta)
    lines = content.strip("\n").split("\n")
    # First line is the caption, followed by a blank, then '# ---'
    assert lines[0] == sd
    assert lines[1] == ""
    assert lines[2] == "# ---"
    # Metadata lines are comment-prefixed
    for ln in lines[3:]:
        assert ln.startswith("# ")


class _FakeSidecarStorage:
    """Captures the uploaded sidecar text."""

    def __init__(self) -> None:
        self.written: str | None = None

    async def get_file_metadata(self, folder: str, filename: str) -> FileMetadata:
        return FileMetadata(file_id="id:1", revision="rev-1", modified_at=None, size=None)

    async def write_sidecar_text(self, folder: str, filename: str, content: str) -> None:
        self.written = content


async def test_sidecar_with_platform_captions_roundtrips_caption_generated() -> None:
    """#80: platform captions must be persisted as # caption_generated: JSON
    so later Analyze calls can serve the social caption instead of the SD prompt."""
    from publisher_v2.config.schema import (
        ApplicationConfig,
        CaptionFileConfig,
        ContentConfig,
        DropboxConfig,
        OpenAIConfig,
        PlatformsConfig,
        StoragePathConfig,
    )
    from publisher_v2.core.models import ImageAnalysis
    from publisher_v2.services.sidecar import generate_and_upload_sidecar
    from publisher_v2.web.sidecar_parser import parse_sidecar_text

    config = ApplicationConfig(
        dropbox=DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"),
        storage_paths=StoragePathConfig(image_folder="/Photos", archive_folder="archive"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        content=ContentConfig(hashtag_string="", archive=True, debug=False),
        captionfile=CaptionFileConfig(extended_metadata_enabled=False),
    )
    storage = _FakeSidecarStorage()
    analysis = ImageAnalysis(description="d", mood="m", tags=["t"])
    platform_captions = {"telegram": "TG caption", "email": "Email caption?"}

    await generate_and_upload_sidecar(
        storage=storage,  # type: ignore[arg-type]
        config=config,
        filename="img.jpg",
        analysis=analysis,
        sd_caption="sd prompt line",
        model_version="gpt-4o-mini",
        platform_captions=platform_captions,
    )

    assert storage.written is not None
    assert "# caption_generated: {" in storage.written
    sd, meta = parse_sidecar_text(storage.written)
    assert sd == "sd prompt line"
    assert meta is not None
    assert meta["caption_generated"] == platform_captions


# --- #134: editing a caption must not corrupt caption_generated ---------------
#
# Real sidecar writer (generate_and_upload_sidecar), real updater
# (update_sidecar_with_caption) and real parser, on the real DropboxStorage with
# only the Dropbox SDK client faked in memory.


class _InMemoryDropbox:
    def __init__(self, *_args, **_kwargs) -> None:
        self.files: dict[str, bytes] = {}

    def files_upload(self, data: bytes, path: str, **_kwargs) -> None:
        self.files[path] = data

    def files_get_metadata(self, path: str):
        import dropbox

        return dropbox.files.FileMetadata(name=path.rsplit("/", 1)[1], id="id:1", rev="0123456789", size=1)

    def files_download(self, path: str):
        import dropbox
        from dropbox.exceptions import ApiError

        if path not in self.files:
            raise ApiError("rid", dropbox.files.DownloadError.path(dropbox.files.LookupError.not_found), None, None)
        from types import SimpleNamespace

        return None, SimpleNamespace(content=self.files[path])


def _config():
    from publisher_v2.config.schema import (
        ApplicationConfig,
        CaptionFileConfig,
        ContentConfig,
        DropboxConfig,
        OpenAIConfig,
        PlatformsConfig,
        StoragePathConfig,
    )

    return ApplicationConfig(
        dropbox=DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"),
        storage_paths=StoragePathConfig(image_folder="/Photos", archive_folder="archive"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        content=ContentConfig(hashtag_string="", archive=True, debug=False),
        captionfile=CaptionFileConfig(extended_metadata_enabled=True),
    )


async def test_caption_edit_preserves_caption_generated(monkeypatch) -> None:
    from publisher_v2.config.schema import DropboxConfig
    from publisher_v2.core.models import ImageAnalysis
    from publisher_v2.services.sidecar import generate_and_upload_sidecar, update_sidecar_with_caption
    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view
    from publisher_v2.services.storage import DropboxStorage

    monkeypatch.setattr("publisher_v2.services.storage.dropbox.Dropbox", _InMemoryDropbox)
    storage = DropboxStorage(DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"))
    platform_captions = {"telegram": "TG caption — ünïcode", "email": "Email caption?"}
    await generate_and_upload_sidecar(
        storage=storage,
        config=_config(),
        filename="img.jpg",
        analysis=ImageAnalysis(description="d", mood="m", tags=["t"]),
        sd_caption="sd prompt line",
        model_version="gpt-4o-mini",
        platform_captions=platform_captions,
    )
    before = rehydrate_sidecar_view((await storage.download_sidecar_if_exists("/Photos", "img.jpg")).decode())
    assert before["caption_generated"] == platform_captions

    await update_sidecar_with_caption(storage, "/Photos", "img.jpg", "Operator's edited caption")
    await update_sidecar_with_caption(storage, "/Photos", "img.jpg", "Edited again")

    text = (await storage.download_sidecar_if_exists("/Photos", "img.jpg")).decode()
    after = rehydrate_sidecar_view(text)
    assert after["caption_generated"] == platform_captions
    assert after["caption"] == "Edited again"
    assert after["metadata"] == {
        **before["metadata"],
        **{k: after["metadata"][k] for k in ("caption", "caption_edited", "caption_updated_at")},
    }
    assert "{'" not in text  # never a Python repr


def test_build_caption_sidecar_renders_dicts_as_json() -> None:
    import json

    text = build_caption_sidecar("sd", {"caption_generated": {"email": "é"}})
    line = next(line for line in text.splitlines() if line.startswith("# caption_generated: "))
    assert json.loads(line.split(": ", 1)[1]) == {"email": "é"}


def test_malformed_json_metadata_value_is_logged(caplog) -> None:
    import logging

    from publisher_v2.services.sidecar_parser import parse_sidecar_text

    with caplog.at_level(logging.WARNING, logger="publisher_v2.sidecar_parser"):
        _sd, meta = parse_sidecar_text("sd\n\n# ---\n# caption_generated: {'telegram': 'x'}\n")
    assert meta is not None and meta["caption_generated"] == "{'telegram': 'x'}"
    events = [r.getMessage() for r in caplog.records if r.name == "publisher_v2.sidecar_parser"]
    assert any("sidecar_metadata_json_invalid" in e and "caption_generated" in e for e in events)


def test_corrupt_caption_generated_warns_once_per_read(caplog) -> None:
    import logging

    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view

    with caplog.at_level(logging.WARNING, logger="publisher_v2.sidecar_parser"):
        view = rehydrate_sidecar_view("sd\n\n# ---\n# caption_generated: {'telegram': 'x'}\n")
    assert view["caption_generated"] is None
    assert sum("sidecar_metadata_json_invalid" in r.getMessage() for r in caplog.records) == 1
