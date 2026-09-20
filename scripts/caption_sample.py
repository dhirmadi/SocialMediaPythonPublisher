#!/usr/bin/env python3
"""Produce the #146 before/after caption sample for a folder of images.

For each image the script runs the real vision + caption stage twice — once
against a baseline commit's prompt configuration, once against the working
tree's — and writes a Markdown table with both captions per platform, the
trigram similarity between them, and the observed cost (calls and tokens).

It is read-only with respect to storage and state: it never publishes, never
writes a sidecar, never archives and never touches the posted-state cache. It
reads local image files, so it does not need Dropbox or R2 either. The only
outbound calls are to OpenAI (vision + caption), which is the point — the
sample is evidence about real model output.

Usage:

    # The config loader requires all three of these, even though this script
    # touches no storage and no publisher. STORAGE_PATHS and PUBLISHERS can be
    # throwaway values; OPENAI_SETTINGS must carry a real key. PUBLISHERS decides
    # which platforms appear in the table — enable every platform you want
    # evidence for, or the column will simply be missing.
    export STORAGE_PATHS='{"root": "/unused"}'
    export PUBLISHERS='[{"type": "telegram", "channel_id": "@unused"}, {"type": "fetlife", "recipient": "x@example.com"}]'
    export OPENAI_SETTINGS='{"api_key": "sk-..."}'

    PYTHONPATH=publisher_v2/src uv run python scripts/caption_sample.py \\
        --images ~/caption-sample \\
        --baseline 5c086e6 \\
        --out docs_v2/09_Reviews/caption_sample.md

Start with ``--limit 2`` to confirm the wiring before paying for the full run:
20 images cost roughly 80 calls (one vision + one caption per image per side),
and the vision half dominates.

The baseline is checked out into a temporary git worktree; only its static
prompt configuration (config/static/*.yaml) is used, so the comparison isolates
the prompt change rather than mixing in unrelated code differences.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_REL = Path("publisher_v2/src/publisher_v2/config/static")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


@dataclass
class Cost:
    """Observed API cost for one image on one configuration."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, usages: list[Any]) -> None:
        """Record one call per entry; OpenAI omits usage on some responses."""
        for usage in usages or []:
            self.calls += 1
            if usage is None:
                continue
            self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0


@dataclass
class Row:
    image: str
    captions: dict[str, dict[str, str]] = field(default_factory=dict)  # variant -> platform -> caption
    costs: dict[str, Cost] = field(default_factory=dict)
    error: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Before/after caption sample (#146).")
    parser.add_argument("--images", required=True, help="Folder of images to sample (20 for the #146 artifact)")
    parser.add_argument("--baseline", default="5c086e6", help="Commit whose prompt config is the 'before' side")
    parser.add_argument("--out", required=True, help="Markdown file to write")
    parser.add_argument("--limit", type=int, default=20, help="Maximum images to process")
    return parser.parse_args(argv)


def _image_paths(folder: Path, limit: int) -> list[Path]:
    paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    return paths[:limit]


def _git() -> str:
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git not found on PATH")
    return git


def _checkout_baseline_static(commit: str, into: Path) -> Path:
    """Materialise the baseline commit's static config in a temp worktree."""
    try:
        subprocess.run(  # noqa: S603 — fixed argv, commit comes from the operator's own CLI flag
            [_git(), "worktree", "add", "--detach", str(into), commit],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"could not check out {commit}: {exc.stderr.strip()}") from exc
    static = into / STATIC_REL
    if not static.is_dir():
        raise SystemExit(f"{commit} has no {STATIC_REL}")
    return static


async def _caption_once(image: Path, static_dir: Path) -> tuple[dict[str, str], Cost]:
    """Run vision + caption for one image with the given static prompt config.

    The prompt configuration is selected with PV2_STATIC_CONFIG_DIR, the override
    the static loader already supports — nothing in the working tree is moved or
    rewritten.
    """
    from publisher_v2.config.loader import load_application_config
    from publisher_v2.config.static_loader import get_static_config
    from publisher_v2.core.models import CaptionSpec
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI

    os.environ["PV2_STATIC_CONFIG_DIR"] = str(static_dir)
    get_static_config.cache_clear()  # type: ignore[attr-defined]
    config = load_application_config()
    ai = AIService(VisionAnalyzerOpenAI(config.openai), CaptionGeneratorOpenAI(config.openai))
    cost = Cost()
    try:
        image_bytes = await asyncio.to_thread(image.read_bytes)
        analysis, vision_usage = await ai.analyzer.analyze(image_bytes)
        cost.add([vision_usage])
        specs = CaptionSpec.for_platforms(config)
        captions, _sd, usages = await ai.create_multi_caption_pair_from_analysis(analysis, specs)
        cost.add(usages)
        return captions, cost
    finally:
        await ai.aclose()


def _refuse_if_prompts_are_overridden() -> None:
    """A tenant prompt override silently defeats the comparison (#146).

    CaptionGeneratorOpenAI only applies the static YAML caption prompts when the
    tenant config still holds the schema defaults. With a custom system_prompt or
    role_prompt in OPENAI_SETTINGS, both halves would use the same prompt and every
    similarity would come back ~1.00 — after paying for the whole run.
    """
    from publisher_v2.config.loader import load_application_config
    from publisher_v2.config.schema import OpenAIConfig

    config = load_application_config()
    defaults = OpenAIConfig(api_key="x")
    overridden = [
        name
        for name in ("system_prompt", "role_prompt")
        if getattr(config.openai, name, None) != getattr(defaults, name, None)
    ]
    if overridden:
        raise SystemExit(
            "OPENAI_SETTINGS overrides " + ", ".join(overridden) + ": the static caption prompts would be "
            "ignored and both halves of the comparison would use the same prompt. Remove the override "
            "for this run."
        )


def _cell(text: str) -> str:
    """Make a caption safe for one Markdown table cell."""
    return text.replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


def _render(rows: list[Row], baseline: str, platforms: list[str]) -> str:
    from publisher_v2.utils.captions import trigram_jaccard

    lines = [
        "# Caption sample: baseline vs current (#146)",
        "",
        f"Baseline prompt configuration: `{baseline}`. Current: working tree.",
        "",
        "- **Delta** is the trigram Jaccard between this image's two captions: how far the prompt",
        "  change moved the wording. 1.00 means it changed nothing.",
        "- **Prev (baseline)** / **Prev (current)** compare each caption with the previous image's",
        "  caption on the same side. These are the #82 evidence: if the current column is",
        "  consistently lower, the captions repeat themselves less across images.",
        "",
        "| Image | Platform | Baseline caption | Current caption | Delta | Prev (baseline) | Prev (current) |",
        "|---|---|---|---|---|---|---|",
    ]
    previous: dict[str, dict[str, str]] = {"baseline": {}, "current": {}}
    for row in rows:
        if row.error and not row.captions:
            lines.append(f"| `{row.image}` | — | _{row.error}_ | | | | |")
            continue
        for platform in platforms:
            before = row.captions.get("baseline", {}).get(platform, "")
            after = row.captions.get("current", {}).get(platform, "")
            delta = f"{trigram_jaccard(before, after):.2f}" if before and after else "—"
            prev_b = previous["baseline"].get(platform, "")
            prev_c = previous["current"].get(platform, "")
            adjacent_b = f"{trigram_jaccard(before, prev_b):.2f}" if before and prev_b else "—"
            adjacent_c = f"{trigram_jaccard(after, prev_c):.2f}" if after and prev_c else "—"
            note = f" _({row.error})_" if row.error else ""
            lines.append(
                f"| `{row.image}` | {platform} | {_cell(before)}{note} | {_cell(after)} | "
                f"{delta} | {adjacent_b} | {adjacent_c} |"
            )
            if before:
                previous["baseline"][platform] = before
            if after:
                previous["current"][platform] = after

    means = _adjacent_means(rows, platforms)
    if means:
        lines += [
            "",
            "## Mean similarity to the previous image (lower = less repetitive)",
            "",
            "| Platform | Baseline | Current |",
            "|---|---|---|",
        ]
        for platform, (mean_b, mean_c) in means.items():
            lines.append(f"| {platform} | {mean_b:.2f} | {mean_c:.2f} |")

    lines += [
        "",
        "## Observed cost per image",
        "",
        "| Image | Variant | Calls | Prompt tokens | Completion tokens |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        for variant, cost in row.costs.items():
            lines.append(
                f"| `{row.image}` | {variant} | {cost.calls} | {cost.prompt_tokens} | {cost.completion_tokens} |"
            )
    return "\n".join(lines) + "\n"


def _adjacent_means(rows: list[Row], platforms: list[str]) -> dict[str, tuple[float, float]]:
    """Mean similarity between consecutive images, per platform, for each variant."""
    from publisher_v2.utils.captions import trigram_jaccard

    means: dict[str, tuple[float, float]] = {}
    for platform in platforms:
        scores: dict[str, list[float]] = {"baseline": [], "current": []}
        for variant in ("baseline", "current"):
            captions = [r.captions.get(variant, {}).get(platform, "") for r in rows]
            captions = [c for c in captions if c]
            scores[variant] = [trigram_jaccard(a, b) for a, b in zip(captions, captions[1:], strict=False)]
        if scores["baseline"] or scores["current"]:
            means[platform] = (
                sum(scores["baseline"]) / len(scores["baseline"]) if scores["baseline"] else 0.0,
                sum(scores["current"]) / len(scores["current"]) if scores["current"] else 0.0,
            )
    return means


def run(args: argparse.Namespace) -> int:
    folder = Path(args.images).expanduser()
    if not folder.is_dir():
        raise SystemExit(f"not a folder: {folder}")
    images = _image_paths(folder, args.limit)
    if not images:
        raise SystemExit(f"no images ({', '.join(IMAGE_SUFFIXES)}) in {folder}")

    live_static = REPO_ROOT / STATIC_REL
    worktree = Path(tempfile.mkdtemp(prefix="caption-sample-baseline-")) / "tree"

    rows: list[Row] = []
    platforms: set[str] = set()
    try:
        baseline_static = _checkout_baseline_static(args.baseline, worktree)
        _refuse_if_prompts_are_overridden()
        for image in images:
            row = Row(image=image.name)
            for variant, static_dir in (("baseline", baseline_static), ("current", live_static)):
                try:
                    captions, cost = asyncio.run(_caption_once(image, static_dir))
                    row.captions[variant] = captions
                    row.costs[variant] = cost
                    platforms |= set(captions)
                except Exception as exc:  # one bad variant must not discard the other
                    row.error = f"{variant}: {type(exc).__name__}: {exc}"
            rows.append(row)
            print(f"done: {image.name}", file=sys.stderr)  # noqa: T201 — operator-facing progress
    finally:
        os.environ.pop("PV2_STATIC_CONFIG_DIR", None)
        subprocess.run(  # noqa: S603 — fixed argv
            [_git(), "worktree", "remove", "--force", str(worktree)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
        shutil.rmtree(worktree.parent, ignore_errors=True)

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render(rows, args.baseline, sorted(platforms) or ["telegram", "email"]))
    print(json.dumps({"images": len(rows), "out": str(out)}), file=sys.stderr)  # noqa: T201
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
