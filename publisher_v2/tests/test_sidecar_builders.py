from __future__ import annotations

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.utils.captions import (
    build_metadata_phase1,
    build_metadata_phase2,
    build_caption_sidecar,
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


