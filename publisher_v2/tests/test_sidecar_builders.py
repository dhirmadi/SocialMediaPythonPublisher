from __future__ import annotations

from publisher_v2.services.sidecar_parser import parse_sidecar_text
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
    """#134 AC2: a malformed value is kept as raw text and logged, never swallowed.

    This originally used `{'telegram': 'x'}` — a Python repr, which the review
    follow-up now RECOVERS rather than reporting as lost. The criterion is about
    values that cannot be salvaged, so the example is now one that genuinely
    cannot: recovery is covered by its own tests below.
    """
    import logging

    from publisher_v2.services.sidecar_parser import parse_sidecar_text

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        _sd, meta = parse_sidecar_text("sd\n\n# ---\n# caption_generated: {not parseable\n")
    assert meta is not None and meta["caption_generated"] == "{not parseable"
    events = [r.getMessage() for r in caplog.records if r.name == "publisher_v2.services.sidecar_parser"]
    assert any("sidecar_metadata_json_invalid" in e and "caption_generated" in e for e in events)


def test_corrupt_caption_generated_warns_once_per_read(caplog) -> None:
    import logging

    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        view = rehydrate_sidecar_view("sd\n\n# ---\n# caption_generated: {not parseable\n")
    assert view["caption_generated"] is None
    assert sum("sidecar_metadata_json_invalid" in r.getMessage() for r in caplog.records) == 1


def test_a_recovered_legacy_value_is_still_reported_once(caplog) -> None:
    """Recovery must not become silence: the file on disk is still in the broken shape.

    The value is returned intact, so nothing is lost, but one WARNING per read
    records that a sidecar still needs rewriting.
    """
    import logging

    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        view = rehydrate_sidecar_view("sd\n\n# ---\n# caption_generated: {'telegram': 'x'}\n")

    assert view["caption_generated"] == {"telegram": "x"}
    assert sum("sidecar_metadata_legacy_repr_recovered" in r.getMessage() for r in caplog.records) == 1


# --- #134 review follow-up -----------------------------------------------------


def test_multi_line_string_values_survive_the_round_trip() -> None:
    """A caption with a blank line lost everything after the first newline.

    The sidecar is a line-oriented `# key: value` format, so a raw multi-line
    value cannot round-trip; it has to be encoded. This matters as soon as #150
    persists per-platform caption text, which routinely carries line breaks.
    """
    caption = "First line.\n\n#rope #shibari"

    text = build_caption_sidecar("sd", {"caption": caption})
    _, metadata = parse_sidecar_text(text)

    assert metadata is not None
    assert metadata["caption"] == caption


def test_multi_line_values_inside_a_dict_survive_the_round_trip() -> None:
    generated = {"telegram": "Line one.\nLine two.", "email": "Subject line"}

    text = build_caption_sidecar("sd", {"caption_generated": generated})
    _, metadata = parse_sidecar_text(text)

    assert metadata is not None
    assert metadata["caption_generated"] == generated


def test_a_caption_that_merely_starts_with_a_quote_is_left_alone() -> None:
    """The compatibility trap: quoting strings makes `"Hello"` ambiguous.

    An existing sidecar can hold `# caption: "Hello"` meaning a caption with
    literal quotes. JSON-decoding every quoted value would silently strip them.
    Only values carrying a JSON escape — which a multi-line value always does,
    since its newline must be escaped — are decoded.
    """
    quoted = '"Hello"'

    text = build_caption_sidecar("sd", {"caption": quoted})
    _, metadata = parse_sidecar_text(text)

    assert metadata is not None
    assert metadata["caption"] == quoted


def test_old_single_line_sidecars_parse_exactly_as_before() -> None:
    """Nothing about the existing on-disk format changes for values without newlines."""
    text = build_caption_sidecar("sd prompt", {"caption": "A plain caption", "mood": "calm"})

    assert "# caption: A plain caption" in text
    assert "# mood: calm" in text

    _, metadata = parse_sidecar_text(text)
    assert metadata == {"caption": "A plain caption", "mood": "calm"}


def test_a_python_repr_dict_left_by_the_old_builder_is_recovered() -> None:
    """Sidecars already written with `str(dict)` are not repaired by the fix alone.

    Every read of one logged a warning and dropped the per-platform captions.
    The values are recoverable — they are Python literals — so recover them
    instead of asking the operator to regenerate the file.
    """
    corrupt = "sd prompt\n\n# ---\n# caption_generated: {'telegram': 'TG cap', 'email': 'Email cap'}\n"

    _, metadata = parse_sidecar_text(corrupt)

    assert metadata is not None
    assert metadata["caption_generated"] == {"telegram": "TG cap", "email": "Email cap"}


def test_recovery_is_restricted_to_plain_string_mappings(caplog) -> None:
    """`ast.literal_eval` is safe, but the recovery still should not accept anything exotic."""
    import logging

    corrupt = "sd\n\n# ---\n# caption_generated: {'a': ('tuple', 'value')}\n"

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        _, metadata = parse_sidecar_text(corrupt)

    assert metadata is not None
    assert metadata["caption_generated"] == "{'a': ('tuple', 'value')}"
    assert "sidecar_metadata_json_invalid" in caplog.text


def test_an_unrecoverable_value_names_the_file_it_came_from(caplog) -> None:
    """The warning said which key was bad but not which of thousands of files."""
    import logging

    corrupt = "sd\n\n# ---\n# caption_generated: {not parseable at all\n"

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        parse_sidecar_text(corrupt, source="IMG_0042.jpg.txt")

    assert "IMG_0042.jpg.txt" in caplog.text


def test_an_unhashable_literal_does_not_crash_the_parser(caplog) -> None:
    """`ast.literal_eval("{{}}")` raises TypeError, which is not a parse error.

    Sidecars come from Dropbox, nothing wraps these call sites in try/except,
    and four characters on one line would have turned the image listing into a
    500. Before the recovery existed this value was simply kept as raw text.
    """
    import logging

    for hostile in ("{{}}", "{[1]: 2}", "{{1,2}: 3}"):
        text = f"sd\n\n# ---\n# caption_generated: {hostile}\n"

        with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
            _, metadata = parse_sidecar_text(text)

        assert metadata is not None
        assert metadata["caption_generated"] == hostile


def test_every_line_break_python_recognises_is_encoded() -> None:
    """`str.splitlines()` splits on more than \\n, so checking for \\n alone is not enough.

    A value containing \\r, \\x0b, \\x0c, \\x85, U+2028 or U+2029 was still
    truncated at that character, silently and with no warning — the exact bug
    the multi-line fix was meant to close.
    """
    for breaker in ("\r", "\x0b", "\x0c", "\x85", "\u2028", "\u2029"):
        value = f"before{breaker}after"

        text = build_caption_sidecar("sd", {"caption": value})
        _, metadata = parse_sidecar_text(text)

        assert metadata is not None, breaker
        assert metadata["caption"] == value, f"{breaker!r} was not preserved"


def test_a_single_line_caption_containing_a_backslash_sequence_is_untouched() -> None:
    """Quoted + a literal backslash escape must not be mistaken for JSON.

    These read back verbatim before the encoding change, and rewriting them
    would corrupt real captions: a Windows path, an escaped quote, or text that
    merely mentions `\\n`.
    """
    for value in ('"Type \\n for a newline"', '"C:\\\\Users\\\\me"', '"He said \\"hi\\""'):
        text = build_caption_sidecar("sd", {"caption": value})
        _, metadata = parse_sidecar_text(text)

        assert metadata is not None
        assert metadata["caption"] == value, f"{value!r} was rewritten"


def test_recovery_does_not_turn_a_caption_into_a_dict() -> None:
    """Only `caption_generated` was ever written as a mapping by the old builder.

    A caption whose text happens to look like a dict is a string, and turning
    it into one makes it vanish from the UI, which requires `caption` to be a
    str.
    """
    text = "sd\n\n# ---\n# caption: {'a': 'b'}\n"

    _, metadata = parse_sidecar_text(text)

    assert metadata is not None
    assert metadata["caption"] == "{'a': 'b'}"


def test_a_corrupt_marked_value_warns_only_once_per_read(caplog) -> None:
    """The parser and the view both warned for the same unreadable value.

    This originally used a quoted value (`"a" or "b\\n"`). Once the encoded
    form became an explicit `!json ` marker, a merely-quoted value is ordinary
    text and warns nowhere — correctly. A marked value that will not decode is
    the shape that genuinely warns, so the once-per-read guarantee is pinned
    there instead.
    """
    import logging

    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        view = rehydrate_sidecar_view("sd\n\n# ---\n# caption_generated: !json {bad\n")

    assert view["caption_generated"] is None
    assert sum("sidecar_metadata_json_invalid" in r.getMessage() for r in caplog.records) == 1


def test_a_merely_quoted_value_is_ordinary_text_and_warns_nowhere(caplog) -> None:
    """Nothing about a quoted value implies it was encoded, so it is not corruption."""
    import logging

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        _, metadata = parse_sidecar_text('sd\n\n# ---\n# caption: "a" or "b\\n"\n')

    assert metadata is not None
    assert metadata["caption"] == '"a" or "b\\n"'
    assert "sidecar_metadata_json_invalid" not in caplog.text


def test_a_corrupt_marked_value_is_logged_not_swallowed(caplog) -> None:
    """A marked value that will not decode is unambiguous corruption.

    The file itself asserts the value was encoded, so a failed decode cannot be
    mistaken for ordinary text — and silently keeping the raw string is exactly
    what AC2 forbids.
    """
    import logging

    for corrupt in ("!json {bad", "!json 123", '!json "unterminated'):
        caplog.clear()
        text = f"sd\n\n# ---\n# caption: {corrupt}\n"

        with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
            _, metadata = parse_sidecar_text(text, source="IMG_7.jpg.txt")

        assert metadata is not None
        assert metadata["caption"] == corrupt
        assert "sidecar_metadata_json_invalid" in caplog.text, corrupt
        assert "IMG_7.jpg.txt" in caplog.text, corrupt


def test_a_caption_that_starts_with_the_marker_round_trips() -> None:
    """The marker is an on-disk contract, so the builder must escape it too.

    Otherwise a caption literally beginning `!json "` is read back as the
    string it appears to encode, silently losing its prefix and quotes.
    """
    for value in ('!json "hi"', "!json hello", "!json [1,2]"):
        text = build_caption_sidecar("sd", {"caption": value})
        _, metadata = parse_sidecar_text(text)

        assert metadata is not None
        assert metadata["caption"] == value, f"{value!r} did not survive"


def test_an_undetectable_caption_generated_value_is_still_reported(caplog) -> None:
    """A plain string under `caption_generated` is dropped, so it has to be reported.

    The parser cannot warn about it — it is not JSON-looking, not marked and
    not a repr, so as a metadata value it is perfectly well-formed. Only the
    view knows the key must hold a mapping, so the view is where the loss
    becomes visible and must be logged.
    """
    import logging

    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view

    for undetectable in ("plain text", "!json{bad", "[1,2]"):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
            view = rehydrate_sidecar_view(f"sd\n\n# ---\n# caption_generated: {undetectable}\n", source="IMG_9.jpg.txt")

        assert view["caption_generated"] is None, undetectable
        assert sum("sidecar_metadata_json_invalid" in r.getMessage() for r in caplog.records) == 1, undetectable
        assert "IMG_9.jpg.txt" in caplog.text, undetectable


def test_caption_submitted_that_is_not_a_mapping_is_reported_and_dropped(caplog) -> None:
    """#147: the new key gets the same treatment as caption_generated.

    A value that decoded cleanly into the wrong type is lost either way; the
    warning is the only signal an operator gets, so it must not be silent.
    """
    import logging

    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        view = rehydrate_sidecar_view('sd\n\n# ---\n# caption_submitted: ["telegram", "email"]\n')

    assert view["caption_submitted"] is None
    assert any(
        "sidecar_metadata_json_invalid" in r.getMessage() and "caption_submitted" in r.getMessage()
        for r in caplog.records
    ), caplog.text


def test_caption_submitted_roundtrips_as_a_mapping() -> None:
    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view
    from publisher_v2.utils.captions import build_caption_sidecar

    submitted = {"telegram": "Telegram text", "email": "Email text"}
    text = build_caption_sidecar("sd prompt", {"caption_submitted": submitted})

    assert rehydrate_sidecar_view(text)["caption_submitted"] == submitted


def test_sidecar_sd_caption_line_is_flattened_to_one_line() -> None:
    """PUB-051 review (security): since AC5 ``sd_caption`` is raw vision output.

    It is written as line 1 of the sidecar, above the ``# ---`` block, so a
    multi-line value could smuggle in extra ``# key: value`` lines — ``caption``
    or ``alt_text`` that ``_reuse_generated_captions`` and the web layer later
    read back as if the app had written them. The builder must flatten it to one
    line, runs of whitespace collapsed to a single space.
    """
    sd = "rope, skin\n\n# ---\n# alt_text: INJECTED\n# caption: INJECTED"

    text = build_caption_sidecar(sd, {"caption": "A plain caption"})

    first_line = text.split("\n", 1)[0]
    assert first_line == "rope, skin # --- # alt_text: INJECTED # caption: INJECTED"

    _sd, metadata = parse_sidecar_text(text)
    assert metadata is not None
    assert metadata["caption"] == "A plain caption"
    injected = {k: v for k, v in metadata.items() if "INJECTED" in str(v)}
    assert injected == {}, f"sd_caption injected metadata keys: {injected}"


def test_sidecar_without_sd_prompt_round_trips_metadata() -> None:
    """PUB-051 follow-up: a sidecar with no SD prompt has an empty first line and still round-trips.

    Decided: generated captions are persisted even without an SD prompt, so the
    AC7 partial retry can reuse them. The empty first line must read back as no
    SD prompt (None or empty), never as a caption (#80), with the metadata intact.
    """
    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view

    meta = {
        "image_file": "a.jpg",
        "caption_generated": {"telegram": "Cold floorboards, warm hands.", "email": "One frayed end."},
        "caption_angles": {"telegram": "craft", "email": "moment"},
    }

    text = build_caption_sidecar("", meta)

    lines = text.splitlines()
    assert lines[0] == "", f"first line should be the empty SD prompt, got {lines[0]!r}"
    assert lines[1] == ""
    assert lines[2] == "# ---"
    view = rehydrate_sidecar_view(text)
    assert not view["sd_caption"], view["sd_caption"]
    assert view["caption"] is None, "the empty SD line must never be served as a caption"
    assert view["has_sidecar"] is True
    assert view["caption_generated"] == meta["caption_generated"]
    assert view["caption_angles"] == meta["caption_angles"]
    assert view["metadata"]["image_file"] == "a.jpg"
