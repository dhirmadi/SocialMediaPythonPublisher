#!/usr/bin/env python3
r"""Caption evaluation harness (PUB-049).

Three modes, one script:

``--offline`` (the CI mode)
    Reads the committed fixtures only. It re-renders every fixture analysis
    through the real ``CaptionGeneratorOpenAI._build_multi_prompt`` as a
    rendering-regression smoke check, scores the committed ``snapshot.json``
    with ``publisher_v2.utils.caption_metrics``, prints the score table, and
    exits non-zero when any metric crosses its bar in ``caption_eval_thresholds
    .json``. It makes zero network calls, needs no API key, and touches no
    storage, publisher, state or cache — it only reads files.

``--nightly`` (the budgeted mode)
    Regenerates ``snapshot.json`` for the twenty fixture analyses with the real
    caption generator (``OPENAI_API_KEY`` from the environment, as every other
    script here reads it), scores it, and writes ``snapshot.json`` plus a
    ``report.md`` holding the score table and the diff against the committed
    snapshot into ``--out``. It writes files and nothing else: opening a change
    request from those files is the scheduled workflow's job, not this script's.
    This script holds no forge credentials and calls no forge API.

``--generate-thresholds`` (the deliberate, human-invoked mode)
    Scores a snapshot and writes the derived bars to ``--out``. Never run as
    part of a nightly regeneration: a snapshot and the bars derived from it must
    move in separate, reviewed steps, or ordinary run-to-run model variance
    silently re-baselines CI.

Usage::

    PYTHONPATH=publisher_v2/src uv run python scripts/caption_eval.py --offline
    PYTHONPATH=publisher_v2/src uv run python scripts/caption_eval.py --nightly --out build/caption-eval
    PYTHONPATH=publisher_v2/src uv run python scripts/caption_eval.py --generate-thresholds \\
        --snapshot publisher_v2/tests/fixtures/captions/snapshot.json \\
        --out publisher_v2/tests/fixtures/captions/caption_eval_thresholds.json
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import difflib
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = REPO_ROOT / "publisher_v2" / "tests" / "fixtures" / "captions"
DEFAULT_SNAPSHOT = DEFAULT_FIXTURES / "snapshot.json"
DEFAULT_THRESHOLDS = DEFAULT_FIXTURES / "caption_eval_thresholds.json"

if str(REPO_ROOT / "publisher_v2" / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "publisher_v2" / "src"))

from publisher_v2.core.exceptions import AIServiceError  # noqa: E402
from publisher_v2.core.models import CaptionSpec, ImageAnalysis  # noqa: E402
from publisher_v2.utils import caption_metrics as metrics  # noqa: E402

# Metrics whose bar is crossed by rising, and those crossed by falling (AC4).
MAX_METRICS: tuple[str, ...] = (
    "opener_closer_trigram_share",
    "two_sentence_emoji_rhythm_share",
    "tells_lexicon_hit_rate",
    "tfidf_bigram_cosine",
    "vision_field_overlap",
)
MIN_METRICS: tuple[str, ...] = (
    "sentence_count_variance",
    "word_count_variance",
    "distinct_1",
    "distinct_2",
)

# The multiplicative margin ``--generate-thresholds`` applies (spec AC6).
MARGIN = 0.10
# NON-DEGENERACY FLOOR for a "max" bar derived from a score of exactly 0.0.
# 0.0 * 1.1 is still 0.0, and the gate compares with strict ``score > value``,
# so such a bar fails on ANY nonzero score at all. The floor stops that.
#
# It is NOT a tolerance and buys no meaningful headroom: the snapshot pools 60
# captions, so the smallest nonzero rate a "max" metric can report is 1/60 =
# 0.0167, already above this floor. Do not read it as "a same-quality re-run
# cannot go red" — for the zero-scoring metrics, a re-run that trips the metric
# even once IS red, which is the intended strictness.
#
# A "min" bar of 0.0 needs no floor: ``0.0 < 0.0`` is false, so it is not
# degenerate.
ZERO_BAR_EPSILON = 0.01


# --- fixtures ---------------------------------------------------------------


def load_analyses(fixtures: Path) -> dict[str, ImageAnalysis]:
    """Load every ``analyses/*.json`` field dump, keyed by its stem (``a01``...)."""
    known = {f.name for f in dataclasses.fields(ImageAnalysis)}
    analyses: dict[str, ImageAnalysis] = {}
    for path in sorted((fixtures / "analyses").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        analyses[path.stem] = ImageAnalysis(**{k: v for k, v in raw.items() if k in known})
    return analyses


def load_history(fixtures: Path) -> dict[str, list[str]]:
    """Load the per-platform published-caption history fixtures."""
    history: dict[str, list[str]] = {}
    for path in sorted((fixtures / "history").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        history[raw.get("platform", path.stem)] = list(raw.get("captions", []))
    return history


def build_specs(platforms: list[str]) -> dict[str, CaptionSpec]:
    """Build a :class:`CaptionSpec` per platform from the real static registry."""
    from publisher_v2.config.static_loader import get_static_config

    registry = get_static_config().ai_prompts.platform_captions
    specs: dict[str, CaptionSpec] = {}
    for platform in platforms:
        entry = registry.get(platform) or registry["generic"]
        specs[platform] = CaptionSpec(
            platform=platform,
            style=entry.style,
            hashtags="" if not entry.hashtags else str(entry.hashtags),
            max_length=entry.max_length,
            guidance=entry.guidance,
            closing=entry.closing,
        )
    return specs


def role_prompt() -> str:
    """The real caption role prompt from the static config."""
    from publisher_v2.config.static_loader import get_static_config

    return get_static_config().ai_prompts.caption.role or ""


# --- scoring ----------------------------------------------------------------


def score_snapshot(snapshot: dict[str, Any], fixtures: Path) -> dict[str, float]:
    """Score a snapshot into the nine-metric table the thresholds file mirrors.

    Set-level metrics run over every caption in the snapshot; the two
    per-caption metrics (TF-IDF cosine to that platform's history, overlap with
    the caption's own vision analysis) are averaged over the snapshot.
    """
    analyses = load_analyses(fixtures)
    history = load_history(fixtures)

    captions: list[str] = []
    cosines: list[float] = []
    overlaps: list[float] = []
    for entry in snapshot.get("entries", []):
        analysis = analyses.get(str(entry.get("analysis", "")))
        for platform, caption in (entry.get("captions") or {}).items():
            if not caption:
                continue
            captions.append(caption)
            if history.get(platform):
                cosines.append(metrics.tfidf_bigram_cosine(caption, history[platform]))
            if analysis is not None:
                overlaps.append(metrics.vision_field_overlap(caption, analysis))

    variance = metrics.sentence_word_count_variance(captions)
    return {
        "opener_closer_trigram_share": metrics.opener_closer_trigram_share(captions),
        "two_sentence_emoji_rhythm_share": metrics.two_sentence_emoji_rhythm_share(captions),
        "tells_lexicon_hit_rate": metrics.tells_lexicon_hit_rate(captions),
        "tfidf_bigram_cosine": (sum(cosines) / len(cosines)) if cosines else 0.0,
        "vision_field_overlap": (sum(overlaps) / len(overlaps)) if overlaps else 0.0,
        "sentence_count_variance": variance["sentence_count_variance"],
        "word_count_variance": variance["word_count_variance"],
        "distinct_1": metrics.distinct_n(captions, 1),
        "distinct_2": metrics.distinct_n(captions, 2),
    }


def direction_for(metric: str) -> str:
    """``"min"`` when falling is the regression, ``"max"`` when rising is."""
    return "min" if metric in MIN_METRICS else "max"


def generate_thresholds(scores: dict[str, float]) -> dict[str, dict[str, Any]]:
    """Derive the thresholds file from a snapshot's score table (AC6).

    The margin always points the way that lets the snapshot which produced
    ``scores`` pass, so the bootstrap run is not immediately red:
    ``direction "max"`` gets ``value * 1.1``, ``direction "min"`` gets
    ``value * 0.9`` (never below zero).

    Deliberate deviation from the spec's literal "±10%", in one degenerate case
    only: a "max" bar derived from a score of exactly 0.0 would be 0.0, which
    fails on any nonzero score at all, so it is raised to
    :data:`ZERO_BAR_EPSILON`. That is a non-degeneracy floor, not a tolerance —
    see the constant. Ordinary nonzero arithmetic stays exactly ±10%, and a
    "min" bar of 0.0 is left alone because it is not degenerate.
    """
    thresholds: dict[str, dict[str, Any]] = {}
    for metric, score in scores.items():
        if direction_for(metric) == "max":
            value = score * (1.0 + MARGIN)
            if score == 0.0:
                value = ZERO_BAR_EPSILON
        else:
            value = max(0.0, score * (1.0 - MARGIN))
        thresholds[metric] = {"direction": direction_for(metric), "value": round(float(value), 6)}
    return thresholds


def _bar_value(metric: str, bar: Any) -> float | None:
    """Return the usable bar value for ``metric``, or ``None`` if the bar cannot gate it.

    ``direction_for(metric)`` — backed by ``MIN_METRICS``/``MAX_METRICS`` — is
    the code-side authority on a metric's direction, so the thresholds file is a
    source of *values*, not of *directions*: the direction of a metric is a
    property of the metric, not a tunable. A bar that declares a direction
    contradicting the code, omits it, or carries a non-numeric value is
    therefore not a bar at all, and the caller treats it exactly like a missing
    one. Deliberately not a distinct failure category — the operator needs the
    metric's name either way, and "this metric is not being gated" is the same
    fact.
    """
    if not isinstance(bar, dict) or bar.get("direction") != direction_for(metric):
        return None
    value = bar.get("value")
    # bool is an int subclass; a JSON ``true`` is not a threshold.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return None if math.isnan(value) or math.isinf(value) else value


def check_thresholds(scores: dict[str, float], thresholds: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return ``(metrics over their bar, metrics no usable bar gates)``.

    AC4 says the thresholds file carries one entry per metric. A metric whose
    entry is missing — or present but unusable, see :func:`_bar_value` — is
    gated by nothing, so it is collected as a failure in its own right rather
    than skipped: otherwise a one-line edit to the thresholds file silently
    un-gates a metric while the run keeps printing a score table and exiting 0,
    a harness reporting success while measuring nothing. Malformed input is
    reported, never raised: a traceback is fail-closed but does not tell the
    operator which metric broke.
    """
    crossed: list[str] = []
    ungated: list[str] = []
    for metric, score in scores.items():
        value = _bar_value(metric, thresholds.get(metric))
        if value is None:
            ungated.append(metric)
            continue
        if (direction_for(metric) == "max" and score > value) or (direction_for(metric) == "min" and score < value):
            crossed.append(metric)
    return crossed, ungated


def format_table(scores: dict[str, float], thresholds: dict[str, Any] | None = None) -> str:
    """Render the score table an operator (or a CI log) reads."""
    lines = ["| Metric | Direction | Score | Bar |", "|---|---|---|---|"]
    for metric in (*MAX_METRICS, *MIN_METRICS):
        if metric not in scores:
            continue
        value = _bar_value(metric, (thresholds or {}).get(metric))
        bar_cell = f"{value:.4f}" if value is not None else "—"
        lines.append(f"| {metric} | {direction_for(metric)} | {scores[metric]:.4f} | {bar_cell} |")
    return "\n".join(lines)


# --- the render smoke check -------------------------------------------------


def render_prompts(fixtures: Path) -> None:
    """Re-render every fixture analysis through the real prompt builder.

    A smoke check, never a metric: it is not scored against the thresholds file,
    it only has to fail the run when the builder raises.
    """
    from publisher_v2.services.ai import CaptionGeneratorOpenAI

    history = load_history(fixtures)
    specs = build_specs(sorted(history) or ["telegram"])
    role = role_prompt()
    for name, analysis in load_analyses(fixtures).items():
        try:
            # Resolved through the class at call time, so a broken builder is
            # seen here rather than through an alias captured at import.
            CaptionGeneratorOpenAI._build_multi_prompt(role, analysis, specs, history)
        except Exception as exc:
            raise RuntimeError(f"prompt render failed for {name}: {exc}") from exc


# --- caption generation (nightly only) --------------------------------------


def build_generator() -> Any:
    """Build the real caption generator. The single seam the nightly mode uses.

    Nothing else in this script constructs an API client, so the offline mode
    cannot reach the network even by accident, and tests replace exactly this.
    """
    from publisher_v2.config.loader import load_application_config
    from publisher_v2.services.ai import CaptionGeneratorOpenAI

    try:
        config = load_application_config()
    except Exception as exc:  # noqa: BLE001 — see below; the type does not matter, the payload does
        # A malformed key makes pydantic render the offending value in its
        # ValidationError (``input_value='...'``). That is raw key material on
        # an error path, which is exactly where a leak survives unnoticed.
        # Name the variable, never the value, and never chain the original.
        raise SystemExit(
            f"could not load configuration ({type(exc).__name__}). Check OPENAI_API_KEY and the other "
            "environment variables; the underlying error is withheld because it can quote the value."
        ) from None
    return CaptionGeneratorOpenAI(config.openai)


async def _generate_snapshot(generator: Any, fixtures: Path) -> dict[str, Any]:
    """Caption every fixture analysis once, returning the snapshot payload."""
    history = await asyncio.to_thread(load_history, fixtures)
    specs = await asyncio.to_thread(build_specs, sorted(history) or ["telegram"])
    analyses = await asyncio.to_thread(load_analyses, fixtures)
    entries: list[dict[str, Any]] = []
    for name, analysis in analyses.items():
        captions, _sd = await generator.generate_multi(analysis, specs, history=history)
        entries.append({"analysis": name, "captions": dict(captions)})
    return {"entries": entries}


# --- modes ------------------------------------------------------------------


def run_offline(fixtures: Path, snapshot_path: Path, thresholds_path: Path) -> int:
    """Render check plus threshold check over a committed snapshot. Zero network calls."""
    try:
        render_prompts(fixtures)
    except Exception as exc:
        print(f"prompt render regression: {exc}")  # noqa: T201 — operator/CI facing
        return 2
    print("prompt render: ok")  # noqa: T201

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))
    scores = score_snapshot(snapshot, fixtures)
    print(format_table(scores, thresholds))  # noqa: T201

    crossed, ungated = check_thresholds(scores, thresholds)
    if ungated:
        print("NO BAR (metric ungated by the thresholds file): " + ", ".join(sorted(ungated)))  # noqa: T201
    if crossed:
        print("REGRESSION: " + ", ".join(sorted(crossed)))  # noqa: T201
    if crossed or ungated:
        return 1
    print("all metrics within their bars")  # noqa: T201
    return 0


def run_nightly(fixtures: Path, out_dir: Path) -> int:
    """Regenerate the snapshot with the real generator and write the report to disk."""
    generator = build_generator()
    try:
        snapshot = asyncio.run(_generate_snapshot(generator, fixtures))
    except AIServiceError as exc:
        # Every caption failure reaches here as AIServiceError, and its message
        # interpolates the upstream error — which for a rejected key carries
        # OpenAI's own partial mask of that key. Not usable material, but the
        # script's failure output should be uniformly clean, so it gets the same
        # message-only treatment as a config failure. Only AIServiceError is
        # caught: anything else is a real bug and must keep its traceback.
        raise SystemExit(
            f"caption generation failed ({type(exc).__name__}). Check OPENAI_API_KEY, the model name and the "
            "account's budget; the underlying error is withheld because it can quote key material."
        ) from None
    out_dir.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    (out_dir / "snapshot.json").write_text(new_text, encoding="utf-8")

    scores = score_snapshot(snapshot, fixtures)
    committed_path = fixtures / "snapshot.json"
    committed_text = committed_path.read_text(encoding="utf-8") if committed_path.is_file() else ""
    diff = "\n".join(
        difflib.unified_diff(
            committed_text.splitlines(),
            new_text.splitlines(),
            fromfile="committed snapshot.json",
            tofile="regenerated snapshot.json",
            lineterm="",
        )
    )
    report = "\n".join(
        [
            "# Caption evaluation: nightly regeneration (PUB-049)",
            "",
            "## Scores",
            "",
            format_table(scores),
            "",
            "Thresholds are deliberately NOT regenerated here: re-baselining the bars",
            "is a separate, human-invoked `--generate-thresholds` run.",
            "",
            "## Snapshot diff",
            "",
            "```diff",
            diff or "(no change)",
            "```",
            "",
        ]
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(format_table(scores))  # noqa: T201
    print(f"wrote {out_dir / 'snapshot.json'} and {out_dir / 'report.md'}")  # noqa: T201
    return 0


def run_generate_thresholds(fixtures: Path, snapshot_path: Path, out_path: Path) -> int:
    """Score a snapshot and write the derived bars to ``out_path``."""
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    scores = score_snapshot(snapshot, fixtures)
    thresholds = generate_thresholds(scores)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(thresholds, indent=2) + "\n", encoding="utf-8")
    print(format_table(scores, thresholds))  # noqa: T201
    print(f"wrote {out_path}")  # noqa: T201
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the CLI arguments; see the module docstring for the three modes."""
    parser = argparse.ArgumentParser(description="Caption evaluation harness (PUB-049).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="Score the committed snapshot; no network calls")
    mode.add_argument("--nightly", action="store_true", help="Regenerate the snapshot with the real generator")
    mode.add_argument("--generate-thresholds", action="store_true", help="Derive the bars from a snapshot")
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURES), help="Fixture directory")
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT), help="Snapshot to score")
    parser.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS), help="Thresholds file to score against")
    parser.add_argument("--out", default=None, help="Output directory (--nightly) or file (--generate-thresholds)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the requested mode and return the process exit code."""
    args = parse_args(argv)
    fixtures = Path(args.fixtures)
    if args.offline:
        return run_offline(fixtures, Path(args.snapshot), Path(args.thresholds))
    if args.nightly:
        if not args.out:
            raise SystemExit("--nightly needs --out DIR")
        return run_nightly(fixtures, Path(args.out))
    if not args.out:
        raise SystemExit("--generate-thresholds needs --out FILE")
    return run_generate_thresholds(fixtures, Path(args.snapshot), Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
