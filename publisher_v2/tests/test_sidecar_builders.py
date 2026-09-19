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
