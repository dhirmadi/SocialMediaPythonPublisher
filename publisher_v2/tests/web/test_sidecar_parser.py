from __future__ import annotations

from publisher_v2.web.sidecar_parser import parse_sidecar_text, rehydrate_sidecar_view


def test_parse_sidecar_empty() -> None:
    sd, meta = parse_sidecar_text("")
    assert sd is None
    assert meta is None


def test_parse_sidecar_basic_metadata() -> None:
    content = (
        "fine-art portrait\n"
        "\n"
        "# ---\n"
        "# image_file: test.jpg\n"
        "# sha256: abc123\n"
        "# tags: [\"a\", \"b\"]\n"
    )
    sd, meta = parse_sidecar_text(content)
    assert sd == "fine-art portrait"
    assert meta is not None
    assert meta["image_file"] == "test.jpg"
    assert meta["sha256"] == "abc123"
    assert meta["tags"] == ["a", "b"]


def test_rehydrate_sidecar_view_prefers_metadata_caption() -> None:
    content = (
        "sd caption only\n"
        "\n"
        "# ---\n"
        "# caption: human caption\n"
        "# tags: [\"x\"]\n"
    )
    view = rehydrate_sidecar_view(content)
    assert view["sd_caption"] == "sd caption only"
    assert view["caption"] == "human caption"
    assert view["metadata"] is not None
    assert view["has_sidecar"] is True


def test_rehydrate_sidecar_view_falls_back_to_sd_caption() -> None:
    content = (
        "sd caption only\n"
        "\n"
        "# ---\n"
        "# image_file: test.jpg\n"
    )
    view = rehydrate_sidecar_view(content)
    assert view["sd_caption"] == "sd caption only"
    assert view["caption"] == "sd caption only"
    assert view["has_sidecar"] is True

