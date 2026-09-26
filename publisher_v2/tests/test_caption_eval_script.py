"""PUB-049 AC3-AC6: ``scripts/caption_eval.py``.

The script is loaded by path the same way ``test_caption_sample_script.py``
loads ``scripts/caption_sample.py`` — ``scripts/`` is not an importable package.

Interface this file pins (the implementer must match it):

- ``main(argv: list[str]) -> int`` — the process exit code.
- ``--offline [--fixtures DIR] [--snapshot PATH] [--thresholds PATH]``
- ``--nightly --out DIR [--fixtures DIR]``
- ``--generate-thresholds --snapshot PATH --out PATH``
- ``generate_thresholds(scores: dict[str, float]) -> dict`` — pure, no I/O.
- ``build_service()`` — the single seam the nightly uses; it wraps
  ``build_generator()`` in the real ``AIService`` so the #82 similarity gate
  runs, since the snapshot must measure published output, not the draft
  used by ``--nightly``. Tests replace it; nothing else in the script may
  construct an OpenAI client.
- The offline prompt-render check must call
  ``CaptionGeneratorOpenAI._build_multi_prompt`` through the class at call
  time (not via a module-level alias captured at import), so the render
  failure below can be injected.

Snapshot schema (``snapshot.json``)::

    {"entries": [{"analysis": "a01", "captions": {"telegram": "...", ...}}, ...]}

Thresholds schema (AC4)::

    {"<metric>": {"direction": "max"|"min", "value": <float>}}
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "captions"

# Metrics whose bar is crossed by going UP vs by going DOWN (AC4/AC6).
MAX_METRICS = {
    "opener_closer_trigram_share",
    "two_sentence_emoji_rhythm_share",
    "tells_lexicon_hit_rate",
    "tfidf_bigram_cosine",
    "vision_field_overlap",
}
MIN_METRICS = {
    "sentence_count_variance",
    "word_count_variance",
    "distinct_1",
    "distinct_2",
}


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("caption_eval", REPO_ROOT / "scripts" / "caption_eval.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["caption_eval"] = module
    spec.loader.exec_module(module)
    return module


def _write_snapshot(path: Path, captions_by_platform: dict[str, str], count: int = 3) -> None:
    """A minimal snapshot in the committed schema, written somewhere disposable."""
    entries = [{"analysis": f"a{i + 1:02d}", "captions": dict(captions_by_platform)} for i in range(count)]
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2))


def _write_permissive_thresholds(path: Path) -> None:
    """Bars nothing can cross, so only a real failure can fail the run."""
    thresholds = {name: {"direction": "max", "value": 1.0} for name in MAX_METRICS}
    thresholds |= {name: {"direction": "min", "value": 0.0} for name in MIN_METRICS}
    path.write_text(json.dumps(thresholds, indent=2))


def _service_around(generator: Any) -> Any:
    """Wrap a canned generator in the REAL AIService, so the real gate runs.

    The rate is pinned high on purpose: ``AIService`` otherwise builds a limiter
    from the static 20/min budget, and a 20-image snapshot would spend minutes
    asleep in a unit test. The gate logic under test is unaffected by the rate.
    """
    from publisher_v2.config.runtime_settings import RuntimeSettings
    from publisher_v2.services.ai import AIService

    return AIService(
        analyzer=object(),
        generator=generator,
        settings=RuntimeSettings(ai_rate_per_minute=100_000),
    )


class _CannedGenerator:
    """Stands in for the OpenAI caption generator in ``--nightly`` (mock boundary)."""

    sd_caption_enabled = False
    sd_caption_single_call_enabled = False

    def __init__(self) -> None:
        self.calls = 0

    async def generate_multi(
        self, analysis, specs, history=None, voice_examples=None, diversity_clause=None, directives=None
    ):
        self.calls += 1
        n = self.calls
        return {
            platform: f"Canned caption {n} for {platform}. Nothing here echoes the stored history."
            for platform in specs
        }, None


# --- AC3: offline mode is offline, fast, and re-renders the real prompt ---


def test_offline_mode_makes_zero_network_calls_and_completes_under_ten_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No key, and any attempt to build an OpenAI client blows up the test."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    snapshot = tmp_path / "snapshot.json"
    thresholds = tmp_path / "thresholds.json"
    _write_snapshot(snapshot, {"telegram": "Rope, then quiet.", "email": "A cold floor and a warm lamp."})
    _write_permissive_thresholds(thresholds)

    mod = _module()

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("offline mode attempted to construct an OpenAI client")

    with patch("openai.AsyncOpenAI", _explode), patch("openai.OpenAI", _explode):
        started = time.monotonic()
        code = mod.main(
            [
                "--offline",
                "--fixtures",
                str(FIXTURES),
                "--snapshot",
                str(snapshot),
                "--thresholds",
                str(thresholds),
            ]
        )
        elapsed = time.monotonic() - started

    assert code == 0
    assert elapsed < 10.0, f"offline mode took {elapsed:.1f}s; AC3 caps it at ten seconds"

    out = capsys.readouterr().out
    # A score table the operator can read, one line per metric.
    for metric in MAX_METRICS | MIN_METRICS:
        assert metric in out, f"{metric} missing from the offline score table"


def test_offline_mode_fails_loudly_when_prompt_rendering_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The render half exercises the real ``_build_multi_prompt``; a broken prompt must fail here.

    The render is a smoke check, not a metric: it must never be scored against
    the thresholds file, it must just fail the run.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    snapshot = tmp_path / "snapshot.json"
    thresholds = tmp_path / "thresholds.json"
    _write_snapshot(snapshot, {"telegram": "Rope, then quiet."})
    _write_permissive_thresholds(thresholds)

    mod = _module()

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("prompt template exploded")

    with patch("publisher_v2.services.ai.CaptionGeneratorOpenAI._build_multi_prompt", _boom):
        code = mod.main(
            [
                "--offline",
                "--fixtures",
                str(FIXTURES),
                "--snapshot",
                str(snapshot),
                "--thresholds",
                str(thresholds),
            ]
        )

    assert code != 0, "a prompt that cannot render must fail the offline run"
    captured = capsys.readouterr()
    assert "prompt template exploded" in captured.out + captured.err


# --- AC4: thresholds decide the exit code ---


def test_offline_mode_exits_nonzero_and_names_metric_on_threshold_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A snapshot full of tells against a zero tells bar must exit non-zero and say which metric."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    snapshot = tmp_path / "snapshot.json"
    thresholds = tmp_path / "thresholds.json"
    _write_snapshot(
        snapshot,
        {
            "telegram": "There is something about the rope tonight. This isn't just knotwork.",
            "email": "In a world where everything rushes, a testament to patience.",
        },
    )
    _write_permissive_thresholds(thresholds)
    bars = json.loads(thresholds.read_text())
    bars["tells_lexicon_hit_rate"] = {"direction": "max", "value": 0.0}
    thresholds.write_text(json.dumps(bars, indent=2))

    mod = _module()
    code = mod.main(
        ["--offline", "--fixtures", str(FIXTURES), "--snapshot", str(snapshot), "--thresholds", str(thresholds)]
    )

    assert code != 0, "a metric over its bar must fail the build"
    output = capsys.readouterr()
    assert "tells_lexicon_hit_rate" in output.out + output.err, "the offending metric must be named"


def test_offline_mode_fails_when_a_threshold_bar_is_malformed_or_inverted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wrong bar must fail the run as loudly as an absent one (AC4).

    The ungated-metric check catches a bar that is *missing*. It does not catch
    a bar that is *wrong*, and ``caption_eval_thresholds.json`` is checked-in
    JSON that future caption PRs will hand-edit. Each shape below is a one-line
    edit that currently leaves the run green (or crashes it with a raw
    traceback) while the metric is effectively un-gated — which would make the
    spec's Success Metric, "CI fails on a branch whose snapshot regresses any
    metric", false.

    ``direction_for(metric)`` — backed by ``MIN_METRICS``/``MAX_METRICS`` — is
    the code-side authority on each metric's direction. A bar whose
    ``direction`` disagrees with it, or is absent, or whose ``value`` is not a
    number, folds into the same ``ungated`` failure path: exit non-zero, name
    the metric. A ``KeyError``/``ValueError`` traceback is fail-closed but is
    not an acceptable contract — an operator cannot tell which metric broke.

    Not in the handoff's test table; record it in PUB-049_summary.md against
    AC4.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    snapshot = tmp_path / "snapshot.json"
    _write_snapshot(snapshot, {"telegram": "Rope, then quiet.", "email": "A cold floor and a warm lamp."})

    # distinct_1 is a "min" metric, and the snapshot scores it well above 0.
    malformed_bars = {
        "unknown direction value": {"direction": "minimum", "value": 0.0},
        "direction inverted against direction_for()": {"direction": "max", "value": 1.0},
        "direction key absent": {"value": 0.5},
        "non-numeric value": {"direction": "min", "value": "high"},
    }

    mod = _module()

    for index, (label, bar) in enumerate(malformed_bars.items()):
        thresholds = tmp_path / f"thresholds-{index}.json"
        _write_permissive_thresholds(thresholds)
        bars = json.loads(thresholds.read_text())
        bars["distinct_1"] = bar
        thresholds.write_text(json.dumps(bars, indent=2))

        try:
            code = mod.main(
                ["--offline", "--fixtures", str(FIXTURES), "--snapshot", str(snapshot), "--thresholds", str(thresholds)]
            )
        except Exception as exc:  # noqa: BLE001 — any crash is itself the failure under test
            output = capsys.readouterr()
            pytest.fail(
                f"{label}: crashed with {exc!r} instead of exiting non-zero and naming the metric.\n{output.out}"
            )

        output = capsys.readouterr()
        assert code != 0, f"{label}: a malformed bar leaves distinct_1 un-gated but the run reported success"
        assert "distinct_1" in output.out + output.err, f"{label}: the metric with the bad bar must be named"


def test_build_generator_reports_a_config_failure_without_echoing_the_key(
    monkeypatch: pytest.MonkeyPatch, env_first_config: None
) -> None:
    """A config-load failure must name ``OPENAI_API_KEY`` and withhold its value.

    Pydantic renders the offending value in its ``ValidationError``
    (``input_value='...'``). Chaining or formatting that error into the message
    the script prints would put raw key material on an error path — the one
    place a leak survives unnoticed, because nobody reads a successful run's
    output but everybody pastes a traceback into an issue.

    The first assertion below is deliberate: it proves the leak is real, so
    this test cannot quietly become vacuous if the upstream error text changes.
    """
    canary = "pub049-canary-key-do-not-echo-9f3c1d"
    monkeypatch.setenv("OPENAI_API_KEY", canary)  # no "sk-" prefix -> fails validation

    from publisher_v2.config.loader import load_application_config

    with pytest.raises(Exception) as raw:  # noqa: B017 — the type is pydantic's, the payload is the point
        load_application_config()
    assert canary in str(raw.value), "upstream no longer quotes the key; this test would be vacuous"

    mod = _module()

    with pytest.raises(SystemExit) as excinfo:
        mod.build_generator()

    message = str(excinfo.value)
    assert canary not in message, f"build_generator echoed the key: {message}"
    assert "OPENAI_API_KEY" in message, "the operator still needs to be told which variable to check"


def test_offline_mode_fails_when_a_metric_is_missing_from_the_thresholds_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A metric dropped from the thresholds file must not silently stop being gated (AC4).

    AC4 says the thresholds file carries "one entry per metric". Skipping a
    metric that has no entry means a one-line edit to
    ``caption_eval_thresholds.json`` can quietly un-gate any metric while CI
    keeps reporting success — the harness would print a score table and exit 0
    while measuring nothing. The contract asserted here is the strong one:
    an incomplete thresholds file is itself a failure, exits non-zero, and
    names the metric that has no bar. A warning on stderr with exit 0 is not
    enough, because nothing in CI reads it.

    This is not in the handoff's test table; it closes a gate hole the review
    found. Record it in PUB-049_summary.md against AC4.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    snapshot = tmp_path / "snapshot.json"
    thresholds = tmp_path / "thresholds.json"
    _write_snapshot(snapshot, {"telegram": "Rope, then quiet.", "email": "A cold floor and a warm lamp."})
    _write_permissive_thresholds(thresholds)

    bars = json.loads(thresholds.read_text())
    del bars["distinct_1"]
    thresholds.write_text(json.dumps(bars, indent=2))

    mod = _module()
    code = mod.main(
        ["--offline", "--fixtures", str(FIXTURES), "--snapshot", str(snapshot), "--thresholds", str(thresholds)]
    )

    assert code != 0, "a metric with no bar is ungated; the run must not report success"
    output = capsys.readouterr()
    assert "distinct_1" in output.out + output.err, "the ungated metric must be named"


def test_offline_mode_passes_cleanly_on_the_real_committed_snapshot_and_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The committed ``snapshot.json`` and ``caption_eval_thresholds.json`` must agree on day one.

    Spec Risks: a mismatch between these two artifacts would make CI red from
    the moment they land rather than on a real regression. They are generated
    together (``--generate-thresholds`` from that exact snapshot), so the
    default-argument run must exit 0.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert (FIXTURES / "snapshot.json").is_file(), "committed snapshot.json is missing"
    assert (FIXTURES / "caption_eval_thresholds.json").is_file(), "committed caption_eval_thresholds.json is missing"

    mod = _module()

    assert mod.main(["--offline"]) == 0


# --- AC5: nightly writes to disk and knows nothing about GitHub ---


def test_nightly_mode_regenerates_snapshot_and_writes_diff_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nightly regenerates the snapshot for the 20 fixture analyses and writes a report."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    out_dir = tmp_path / "out"
    mod = _module()
    generator = _CannedGenerator()

    with patch.object(mod, "build_service", lambda: _service_around(generator)):
        code = mod.main(["--nightly", "--fixtures", str(FIXTURES), "--out", str(out_dir)])

    assert code == 0
    snapshot = json.loads((out_dir / "snapshot.json").read_text())
    assert len(snapshot["entries"]) == 20, "one entry per fixture analysis"
    assert generator.calls == 20, "one caption call per analysis, no live calls"
    assert "Canned caption" in json.dumps(snapshot)

    report = (out_dir / "report.md").read_text()
    assert "tells_lexicon_hit_rate" in report, "the score table must be in the report"
    assert "diff" in report.lower(), "AC5 asks for the diff as well as the score table"

    # The report is the PR body a human reads to judge a regenerated snapshot,
    # so every metric must carry the bar it is judged against. Rendering the
    # table without the thresholds leaves every Bar cell as an em dash, which
    # tells the reader a score and nothing to compare it to. Reading the bars
    # is not regenerating them: the nightly still must not write that file.
    committed_bars = json.loads((FIXTURES / "caption_eval_thresholds.json").read_text())
    table = report.split("## Snapshot diff")[0]
    bar_row = next(line for line in table.splitlines() if line.startswith("| tells_lexicon_hit_rate |"))
    assert "—" not in bar_row, f"the nightly report shows no bar to judge the score against: {bar_row}"
    assert f"{float(committed_bars['tells_lexicon_hit_rate']['value']):.4f}" in bar_row, bar_row

    # The committed fixture snapshot must not be touched by a nightly --out run.
    committed = FIXTURES / "snapshot.json"
    if committed.exists():
        assert "Canned caption" not in committed.read_text(), "nightly wrote into the committed fixture"


def test_nightly_mode_never_imports_or_calls_anything_github_shaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR creation is the workflow's job. The script must not hold a token or call the API."""
    source = (REPO_ROOT / "scripts" / "caption_eval.py").read_text().lower()
    for needle in ("github", "gh pr", "pygithub", "api.github.com", "pull_request"):
        assert needle not in source, f"caption_eval.py must not reference {needle!r}"

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-be-read")

    # Scoped to what THIS test imports. A global assertion over sys.modules
    # would go red the day any unrelated test in the session imports a module
    # with "github" in its name — an isolation defect under pytest-randomly,
    # not a flake. AC5's claim is about the eval script, so diff the imports.
    before = set(sys.modules)
    mod = _module()

    with patch.object(mod, "build_service", lambda: _service_around(_CannedGenerator())):
        assert mod.main(["--nightly", "--fixtures", str(FIXTURES), "--out", str(tmp_path / "out")]) == 0

    newly_imported = set(sys.modules) - before
    assert not [name for name in newly_imported if "github" in name.lower()], (
        f"a GitHub client was imported by the eval script: {sorted(newly_imported)}"
    )


# --- AC6: thresholds are derived, not hand-written ---


def test_generate_thresholds_derives_bar_from_snapshot_scores_with_margin(tmp_path: Path) -> None:
    """A fixed score table in, a thresholds file in the AC4 schema out, with a 10% margin.

    The margin always points the way that lets the snapshot that produced the
    scores pass, so the bootstrap run is not immediately red:

      direction "max" (higher is worse): value = score * 1.1
        tells_lexicon_hit_rate 0.20 -> 0.22
        tfidf_bigram_cosine    0.30 -> 0.33
      direction "min" (lower is worse): value = score * 0.9
        distinct_2             0.80 -> 0.72

    The degenerate zero case is pinned below, deliberately asymmetric.
    """
    mod = _module()
    scores = {"tells_lexicon_hit_rate": 0.20, "tfidf_bigram_cosine": 0.30, "distinct_2": 0.80}

    result = mod.generate_thresholds(scores)

    assert result == {
        "tells_lexicon_hit_rate": {"direction": "max", "value": pytest.approx(0.22)},
        "tfidf_bigram_cosine": {"direction": "max", "value": pytest.approx(0.33)},
        "distinct_2": {"direction": "min", "value": pytest.approx(0.72)},
    }

    # A score of exactly 0.0 is where a purely multiplicative margin breaks
    # down, and the two directions break down differently:
    #
    #   "max": 0.0 * 1.1 is still 0.0, and the gate compares with strict
    #     ``score > value``, so such a bar fails on ANY nonzero score at all.
    #     A "max" bar derived from 0.0 therefore gets an absolute floor of
    #     0.01. That floor is a NON-DEGENERACY guard, not a tolerance: the
    #     snapshot pools 60 captions, so the smallest nonzero rate a "max"
    #     metric can report is 1/60 = 0.0167, already above the floor. A
    #     re-run that trips a zero-scoring metric even once is still red, and
    #     that strictness is intended.
    #
    #   "min": 0.0 * 0.9 is 0.0, and the gate compares with strict
    #     ``score < value``. ``0.0 < 0.0`` is false, so the bar is NOT
    #     degenerate and correctly stays at 0.0 — no floor, no epsilon.
    #
    # Without this the epsilon branch can be deleted outright and the suite
    # stays green, since every bar and every committed score collapses to 0.0.
    assert mod.generate_thresholds({"tells_lexicon_hit_rate": 0.0}) == {
        "tells_lexicon_hit_rate": {"direction": "max", "value": pytest.approx(0.01)}
    }
    assert mod.generate_thresholds({"distinct_2": 0.0}) == {
        "distinct_2": {"direction": "min", "value": pytest.approx(0.0)}
    }

    # ...and the CLI mode writes exactly that, scored from a snapshot, to --out.
    snapshot = tmp_path / "snapshot.json"
    out = tmp_path / "caption_eval_thresholds.json"
    _write_snapshot(snapshot, {"telegram": "Rope, then quiet.", "email": "A cold floor and a warm lamp."})

    assert (
        mod.main(["--generate-thresholds", "--fixtures", str(FIXTURES), "--snapshot", str(snapshot), "--out", str(out)])
        == 0
    )

    written = json.loads(out.read_text())
    assert set(written) == MAX_METRICS | MIN_METRICS
    for name, bar in written.items():
        assert bar["direction"] == ("max" if name in MAX_METRICS else "min")
        assert isinstance(bar["value"], float)


# --- PUB-049 review follow-ups (outside the handoff's Test-first table) ---


def test_build_specs_resolves_the_hashtag_flag_the_way_production_does() -> None:
    """``PlatformCaptionStyle.hashtags`` is a BOOL FLAG, not a hashtag string.

    Production resolves it as ``config.content.hashtag_string if
    style_cfg.hashtags else ""`` (``CaptionSpec.for_platforms``). Reading the
    flag as text instead renders the literal line ``Include hashtags: True.``
    into the prompt, so the harness would score captions produced by a prompt
    production never emits — which is the one thing this harness must not do.
    """
    mod = _module()
    specs = mod.build_specs(["telegram", "email", "instagram"])

    for platform, spec in specs.items():
        assert spec.hashtags != "True", f"{platform}: the bool flag leaked into the prompt as text"
        assert spec.hashtags in ("", mod.FIXTURE_HASHTAG_STRING), f"{platform}: {spec.hashtags!r}"
        # A flag that is on must yield real hashtags, not an empty string.
        assert isinstance(spec.hashtags, str)

    # At least one platform in the real registry has the flag on, or this test
    # would pass vacuously on an all-empty registry.
    assert any(spec.hashtags for spec in specs.values()), "no platform exercised the flag-on branch"


def test_the_rendered_prompt_never_carries_the_hashtag_flag_as_text() -> None:
    """End-to-end guard on the same bug, through the real prompt builder."""
    from publisher_v2.services.ai import CaptionGeneratorOpenAI

    mod = _module()
    fixtures = FIXTURES
    history = mod.load_history(fixtures)
    specs = mod.build_specs(sorted(history))
    analysis = next(iter(mod.load_analyses(fixtures).values()))

    prompt, _ = CaptionGeneratorOpenAI._build_multi_prompt(mod.role_prompt(), analysis, specs, history)

    assert "hashtags: True" not in prompt
    assert "hashtags: False" not in prompt


def test_nightly_fills_the_config_the_loader_demands_but_the_harness_never_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nightly workflow supplies only OPENAI_API_KEY; the loader demands more.

    ``load_application_config`` hard-requires STORAGE_PATHS, PUBLISHERS and
    OPENAI_SETTINGS. Without them every scheduled run dies at the first step.
    This harness touches no storage and no publisher, so it fills those with
    placeholders exactly as ``scripts/caption_sample.py`` already does.
    """
    mod = _module()
    for name in ("STORAGE_PATHS", "PUBLISHERS", "OPENAI_SETTINGS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-testkeynotreal1234567890abcdef")

    mod._fill_unused_env()

    for name in ("STORAGE_PATHS", "PUBLISHERS", "OPENAI_SETTINGS"):
        assert os.environ.get(name), f"{name} still unset; the nightly would die on the loader"
    # The key itself is never invented: that one must come from the environment.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        mod._fill_unused_env()
    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_nightly_snapshot_goes_through_the_production_similarity_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot must measure what production publishes, not the pre-gate draft.

    ``AIService.create_multi_caption_pair_from_analysis`` is where the #82
    similarity gate, the structure-directive rotation and the one bounded
    regeneration live. Calling ``generate_multi`` directly skips all of it, so a
    harness built that way systematically under-reports the very machinery the
    prompt PRs added to reduce repetition — the comparison PUB-051/PUB-052 are
    meant to make off these numbers. ``scripts/caption_sample.py`` already makes
    this argument in its own docstring: #82 is code, not just prompt text.

    The generator here hands back a first draft copied verbatim from telegram's
    history, which is far over the 0.45 gate threshold. If the gate runs, the
    snapshot holds the SECOND draft; if it was bypassed, it holds the first.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-testkeynotreal1234567890abcdef")
    history = json.loads((FIXTURES / "history" / "telegram.json").read_text())["captions"]
    duplicated = history[0]

    class _GateTrippingGenerator:
        sd_caption_enabled = False
        sd_caption_single_call_enabled = False

        def __init__(self) -> None:
            self.calls = 0

        async def generate_multi(self, analysis, specs, history=None, **kwargs):
            self.calls += 1
            # First draft per image duplicates history; the regeneration does not.
            text = duplicated if self.calls % 2 == 1 else "A different line entirely, nothing like the last one."
            return {platform: text for platform in specs}, None

    generator = _GateTrippingGenerator()
    service = _service_around(generator)
    out_dir = tmp_path / "out"
    mod = _module()

    with patch.object(mod, "build_service", lambda: service):
        code = mod.main(["--nightly", "--fixtures", str(FIXTURES), "--out", str(out_dir)])

    assert code == 0
    snapshot = json.loads((out_dir / "snapshot.json").read_text())
    telegram = [entry["captions"]["telegram"] for entry in snapshot["entries"]]

    assert duplicated not in telegram, "the pre-gate draft reached the snapshot; the similarity gate was bypassed"
    assert generator.calls > len(snapshot["entries"]), "no regeneration happened, so the gate never ran"


# --- PUB-051 follow-up: the nightly rotates content angles like sequential publishes ---


class _AngleRecordingService:
    """Wraps the REAL AIService and records what each fixture's caption call received and returned.

    The angles come from the real LRU rotation, so the test pins the harness's
    threading of ``history_angles``, not a fake picker.
    """

    def __init__(self, service: Any) -> None:
        import copy
        import inspect

        self._service = service
        self._signature = inspect.signature(service.create_multi_caption_pair_from_analysis)
        self._copy = copy.deepcopy
        self.received: list[dict[str, Any]] = []
        self.returned_angles: list[dict[str, str]] = []

    async def create_multi_caption_pair_from_analysis(self, *args: Any, **kwargs: Any) -> Any:
        bound = self._signature.bind(*args, **kwargs)
        self.received.append(
            {
                "history": self._copy(bound.arguments.get("history")),
                "history_angles": self._copy(bound.arguments.get("history_angles")),
            }
        )
        result = await self._service.create_multi_caption_pair_from_analysis(*args, **kwargs)
        self.returned_angles.append(dict(result[3]))
        return result


def _run_nightly_with_angle_recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Path]:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    out_dir = tmp_path / "out"
    mod = _module()
    recorder = _AngleRecordingService(_service_around(_CannedGenerator()))
    with patch.object(mod, "build_service", lambda: recorder):
        code = mod.main(["--nightly", "--fixtures", str(FIXTURES), "--out", str(out_dir)])
    assert code == 0
    return mod, recorder, out_dir


def test_nightly_threads_angles_across_fixtures_like_sequential_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each fixture is captioned as if the previous fixtures had just been published.

    Production stores the angle of every published caption and the next run
    rotates away from it. The harness must simulate that: after each fixture the
    angles it got are prepended per platform to a running ``history_angles``,
    most-recent-first, capped at the caption-history window. The caption TEXT
    history stays the fixed fixture history, so scores stay comparable with the
    PUB-049 baseline.
    """
    from publisher_v2.config.static_loader import get_static_config

    window = get_static_config().ai_prompts.caption_history.window_size
    mod, recorder, _out = _run_nightly_with_angle_recorder(tmp_path, monkeypatch)
    fixture_history = mod.load_history(FIXTURES)

    assert len(recorder.received) == 20, "one caption call per fixture analysis"
    for index, call in enumerate(recorder.received):
        assert call["history"] == fixture_history, f"fixture {index}: the caption-text history must stay fixed"

    first = recorder.received[0]["history_angles"]
    assert not first or not any(first.values()), f"the first fixture has no prior publishes: {first}"

    for index in range(1, len(recorder.received)):
        received = recorder.received[index]["history_angles"]
        assert received, f"fixture {index}: no history_angles passed; every image gets the same angle"
        for platform in fixture_history:
            expected = [recorder.returned_angles[i][platform] for i in range(index - 1, -1, -1)][:window]
            assert received.get(platform) == expected, (
                f"fixture {index} {platform}: history_angles must be the previous fixtures' angles, "
                f"most-recent-first, capped at {window}; got {received.get(platform)}, expected {expected}"
            )

    for index in range(1, len(recorder.returned_angles)):
        for platform, angle in recorder.returned_angles[index].items():
            assert angle != recorder.returned_angles[index - 1][platform], (
                f"fixtures {index - 1} and {index} both got {angle!r} on {platform}; the pool allows rotation"
            )


def test_nightly_snapshot_records_angles_per_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each snapshot entry carries the angle each platform's kept caption was written under, next to ``captions``."""
    from publisher_v2.utils.captions import CONTENT_ANGLES

    _mod, recorder, out_dir = _run_nightly_with_angle_recorder(tmp_path, monkeypatch)
    snapshot = json.loads((out_dir / "snapshot.json").read_text())

    assert len(snapshot["entries"]) == len(recorder.returned_angles) == 20
    for entry, returned in zip(snapshot["entries"], recorder.returned_angles, strict=True):
        assert "angles" in entry, f"{entry['analysis']}: snapshot entry has no 'angles'"
        assert entry["angles"] == returned, f"{entry['analysis']}: recorded angles differ from the service's"
        assert set(entry["angles"]) == set(entry["captions"]), f"{entry['analysis']}: one angle per captioned platform"
        assert set(entry["angles"].values()) <= set(CONTENT_ANGLES)


def test_nightly_report_includes_angle_distribution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``report.md`` carries an "Angle distribution" section with per-platform counts over the run.

    Format-agnostic on purpose: for every platform and every angle it used,
    some line of the section must name the angle and carry its count (a table
    with angles as rows and platforms as columns satisfies this, as does one
    row per platform/angle pair).
    """
    from collections import Counter

    _mod, recorder, out_dir = _run_nightly_with_angle_recorder(tmp_path, monkeypatch)
    report = (out_dir / "report.md").read_text()

    lowered = report.lower()
    assert "angle distribution" in lowered, "report.md has no 'Angle distribution' section"
    start = lowered.index("angle distribution")
    rest = report[start:]
    next_heading = rest.find("\n## ", 1)
    section = rest if next_heading == -1 else rest[:next_heading]
    lines = section.splitlines()

    platforms = sorted({p for angles in recorder.returned_angles for p in angles})
    for platform in platforms:
        assert platform in section, f"{platform} missing from the angle distribution"
        counts = Counter(angles[platform] for angles in recorder.returned_angles)
        assert sum(counts.values()) == 20
        for angle, count in counts.items():
            assert any(angle in line and str(count) in line for line in lines), (
                f"{platform}: no line in the angle distribution names {angle!r} with its count {count}\n{section}"
            )
