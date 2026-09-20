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

    # Only the API key needs a real value: this script touches no storage and no
    # publisher. The loader nevertheless demands storage and publisher
    # credentials, so the script fills the unused ones with placeholders when
    # they are absent (it says which, on stderr). PUBLISHERS decides which
    # platforms appear in the table — enable every platform you want evidence
    # for, or the column will simply be missing.
    #
    # The key is read from OPENAI_API_KEY, NOT from OPENAI_SETTINGS.api_key.
    export OPENAI_API_KEY='sk-...'

    # Optional; these are what the script would otherwise fill in for you:
    #   STORAGE_PATHS='{"root": "/unused"}'
    #   PUBLISHERS='[{"type": "telegram", "channel_id": "@unused"},
    #                {"type": "fetlife", "recipient": "x@example.com"}]'
    #   DROPBOX_APP_KEY / DROPBOX_APP_SECRET / DROPBOX_REFRESH_TOKEN
    #   TELEGRAM_BOT_TOKEN, EMAIL_PASSWORD, OPENAI_SETTINGS (models and budgets)

    PYTHONPATH=publisher_v2/src uv run python scripts/caption_sample.py \\
        --images ~/caption-sample \\
        --baseline 5c086e6 \\
        --out docs_v2/09_Reviews/caption_sample.md

Start with ``--limit 2`` to confirm the wiring before paying for the full run:
20 images cost roughly 80 calls (one vision + one caption per image per side),
and the vision half dominates.

The baseline is checked out into a temporary git worktree and the baseline half
runs in a subprocess against **that commit's own** ``publisher_v2`` — prompts
and code together. #82 is code (the similarity gate, the history constraints,
the structure-directive rotation), so swapping only the YAML would run both
halves through today's machinery and the table would answer a different
question: "did the prompt text change the wording", not "did #82 reduce
repetition".

Each side is fed its own previous captions as history, so the machinery under
test actually runs.

The baseline worktree is removed on the way out. A run killed outright (SIGKILL)
leaves it registered: ``git worktree prune`` clears that.
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
# How many of a side's own previous captions to feed back as history, per platform.
HISTORY_DEPTH = 5


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
        """Record one call per entry; OpenAI omits usage on some responses.

        This under-counts, and the report says so: ``AIService`` drops ``None``
        usages before returning, so a caption call whose response carried no
        usage payload never reaches here — nor does the silent paid fallback
        from ``generate_multi_with_sd`` to ``generate_multi``. Only the vision
        call, which this script makes itself, is counted whether or not it
        reports usage. The numbers are a floor, not a bill.
        """
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


# Credentials the config loader demands but this script never uses. Filled in
# only when absent, and reported, so the documented invocation actually loads
# instead of failing three times over on storage and publisher secrets.
_UNUSED_ENV_PLACEHOLDERS = {
    "STORAGE_PATHS": '{"root": "/unused"}',
    "PUBLISHERS": '[{"type": "telegram", "channel_id": "@unused"}, '
    '{"type": "fetlife", "recipient": "unused@example.com"}]',
    "DROPBOX_APP_KEY": "unused",
    "DROPBOX_APP_SECRET": "unused",
    "DROPBOX_REFRESH_TOKEN": "unused",
    "TELEGRAM_BOT_TOKEN": "unused",
    "EMAIL_PASSWORD": "unused",
    # Required by the env-first loader even when every model default is fine.
    "OPENAI_SETTINGS": "{}",
}


def _fill_unused_env() -> None:
    filled = [name for name, value in _UNUSED_ENV_PLACEHOLDERS.items() if not os.environ.get(name)]
    for name in filled:
        os.environ[name] = _UNUSED_ENV_PLACEHOLDERS[name]
    if filled:
        print(  # noqa: T201 — operator-facing
            "using placeholders for unused config: " + ", ".join(sorted(filled)),
            file=sys.stderr,
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("set OPENAI_API_KEY — this script makes real API calls, and the loader reads the key there")


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


async def _caption_once(
    image: Path, static_dir: Path, history: dict[str, list[str]] | None = None
) -> tuple[dict[str, str], Cost]:
    """Run vision + caption for one image with the given static prompt config.

    The prompt configuration is selected with PV2_STATIC_CONFIG_DIR, the override
    the static loader already supports — nothing in the working tree is moved or
    rewritten.

    ``history`` is that side's own previous captions, per platform. Without it
    the #82 machinery this artefact is meant to measure — the similarity gate,
    the openings/closings constraints, the structure-directive rotation — never
    runs, and the table measures prompt drift only.
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
        captions, _sd, usages = await ai.create_multi_caption_pair_from_analysis(
            analysis, specs, history=history or None
        )
        cost.add(usages)
        return captions, cost
    finally:
        await ai.aclose()


def _baseline_takes_history(worktree: Path) -> bool:
    """Whether that commit's caption call accepts a ``history`` argument.

    Read before the first paid call: a baseline that ignores history writes a
    more repetitive "before" and flatters the current side, and the runtime
    refusal cannot fire on image 1 (which has no history yet) — so without this
    the run bills both halves of every image before anyone notices.
    """
    source = worktree / "publisher_v2" / "src" / "publisher_v2" / "services" / "ai.py"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return True
    marker = "async def create_multi_caption_pair_from_analysis("
    if marker not in text:
        return True
    signature = text[text.index(marker) : text.index(")", text.index(marker))]
    return "history" in signature


def _baseline_analyze_wants_url(worktree: Path) -> bool:
    """True when that commit's VisionAnalyzerOpenAI refuses bytes."""
    source = worktree / "publisher_v2" / "src" / "publisher_v2" / "services" / "ai.py"
    try:
        return "Byte input not supported" in source.read_text(encoding="utf-8")
    except OSError:
        return False


def _caption_once_at_baseline(
    image: Path, worktree: Path, static_dir: Path, history: dict[str, list[str]] | None
) -> tuple[dict[str, str], Cost]:
    """Run one image through the BASELINE commit's code, not the working tree's.

    The point of the artefact is "did #82 reduce repetition", and #82 is code:
    the similarity gate, the history constraints, the structure directives. Only
    swapping the YAML runs both halves through today's machinery, so the table
    would answer "did the prompt text change the wording" instead. The baseline
    worktree is already checked out, so its ``publisher_v2/src`` goes on
    PYTHONPATH in a subprocess with its own interpreter state.
    """
    worker = worktree / "publisher_v2" / "src"
    payload = {
        "image": str(image),
        "static_dir": str(static_dir),
        "history": history or {},
        # Byte input for vision arrived in 6c0641d; before that, analyze() raises
        # for bytes and wants a URL. Read off the baseline's own source rather
        # than assumed from today's signature.
        "analyze_wants_url": _baseline_analyze_wants_url(worktree),
    }
    env = dict(os.environ)
    env["PYTHONPATH"] = str(worker)
    env["PV2_STATIC_CONFIG_DIR"] = str(static_dir)
    if payload["analyze_wants_url"]:
        # A pre-#93 baseline downloads the URL unless vision_max_dimension is 0,
        # and a data: URL cannot be downloaded, so 0 is the only way in. That is
        # an asymmetry, not a match: today's byte path defaults to 1024 and
        # resizes, so the baseline sees the full-size original while the current
        # side sees a 1024px re-encode, and only the baseline has the quality
        # fallback disabled. Disclosed in the report header rather than hidden.
        settings = json.loads(env.get("OPENAI_SETTINGS") or "{}")
        settings["vision_max_dimension"] = 0
        # The quality-escalation fallback retries with a dimension above 0, which
        # means downloading — and httpx cannot download a data: URL. Without this
        # a transient vision error turns into an UnsupportedProtocol traceback
        # instead of the retry the baseline intended.
        settings["vision_fallback_enabled"] = False
        env["OPENAI_SETTINGS"] = json.dumps(settings)
    proc = subprocess.run(  # noqa: S603 — fixed argv; the payload goes in on stdin
        [sys.executable, "-c", _BASELINE_WORKER, json.dumps(payload)],
        cwd=str(worktree),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = proc.stderr.strip()
        print(tail, file=sys.stderr)  # noqa: T201 — the full text, for the operator only
        # Only the last line reaches the caller: row.error is written into a
        # Markdown file meant for docs_v2, and a traceback from a process whose
        # environment holds the API key is not a redaction boundary.
        last = tail.splitlines()[-1] if tail else "no output"
        raise RuntimeError(f"baseline worker failed: {last[:200]}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    if history and not result.get("history_used"):
        # A baseline that ran without history produces a MORE repetitive "before",
        # which biases the artefact in #82's favour. Refuse rather than report it.
        raise RuntimeError(
            "baseline ran without history: its create_multi_caption_pair_from_analysis "
            "takes no history parameter, so the comparison would flatter the current side"
        )
    cost = Cost(
        calls=result["cost"]["calls"],
        prompt_tokens=result["cost"]["prompt_tokens"],
        completion_tokens=result["cost"]["completion_tokens"],
    )
    return result["captions"], cost


# Runs inside the baseline worktree, against the baseline's own publisher_v2.
_BASELINE_WORKER = """
import asyncio, base64, inspect, json, mimetypes, sys

payload = json.loads(sys.argv[1])

async def _main():
    from publisher_v2.config.loader import load_application_config
    from publisher_v2.config.static_loader import get_static_config
    from publisher_v2.core.models import CaptionSpec
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI

    get_static_config.cache_clear()
    config = load_application_config()
    ai = AIService(VisionAnalyzerOpenAI(config.openai), CaptionGeneratorOpenAI(config.openai))
    calls = prompt_tokens = completion_tokens = 0
    def _add(usages):
        nonlocal calls, prompt_tokens, completion_tokens
        for usage in usages:
            calls += 1
            if usage is not None:
                prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens += getattr(usage, "completion_tokens", 0) or 0
    try:
        with open(payload["image"], "rb") as handle:
            image_bytes = handle.read()
        # The baseline predates byte input (it arrived in 6c0641d): its analyze
        # raises for bytes and wants a URL. A data: URL is the only one that
        # works for a local file, and the baseline passes it through unchanged.
        # Feature-detected rather than assumed, so a newer baseline uses bytes.
        subject = image_bytes
        if payload["analyze_wants_url"]:
            # Such a baseline only passes a URL through untouched when
            # vision_max_dimension == 0; above that it tries to DOWNLOAD the URL,
            # and httpx rejects a data: one. The caller forces 0 for this run,
            # which means this side is NOT resized the way the current side is.
            mime = mimetypes.guess_type(payload["image"])[0] or "image/jpeg"
            subject = "data:" + mime + ";base64," + base64.b64encode(image_bytes).decode("ascii")
        analysis, vision_usage = await ai.analyzer.analyze(subject)
        _add([vision_usage])
        specs = CaptionSpec.for_platforms(config)
        caption_call = ai.create_multi_caption_pair_from_analysis
        # Older baselines have no history parameter. Checked, not caught: an
        # except TypeError here would also swallow one raised inside generation
        # and silently re-run it without history — a second paid call reported
        # as a success.
        takes_history = "history" in inspect.signature(caption_call).parameters
        if takes_history and payload["history"]:
            captions, _sd, usages = await caption_call(analysis, specs, history=payload["history"])
        else:
            captions, _sd, usages = await caption_call(analysis, specs)
        _add(usages)
    finally:
        # aclose() arrived in 989f9e1, after this baseline.
        closer = getattr(ai, "aclose", None)
        if closer is not None:
            await closer()
    print(json.dumps({
        "captions": captions,
        "cost": {
            "calls": calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
        "history_used": bool(takes_history and payload["history"]),
    }))

asyncio.run(_main())
"""


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
        f"Baseline: `{baseline}` — that commit's own code and prompts, run in a subprocess.",
        "Current: the working tree.",
        "",
        "**One asymmetry, deliberate and unavoidable:** a pre-#93 baseline cannot take",
        "image bytes, so its half is given a `data:` URL, which that code only accepts",
        "with `vision_max_dimension = 0` (above 0 it downloads the URL) and with the",
        "quality-escalation fallback off (it retries by downloading). So the baseline",
        "sees the full-size original where the current side sees a 1024px re-encode.",
        'With the default `vision_detail="low"` the practical difference is small, but',
        "it is not nothing.",
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
            lines.append(f"| `{row.image}` | — | _{_cell(row.error)}_ | | | | |")
            continue
        for platform in platforms:
            before = row.captions.get("baseline", {}).get(platform, "")
            after = row.captions.get("current", {}).get(platform, "")
            delta = f"{trigram_jaccard(before, after):.2f}" if before and after else "—"
            prev_b = previous["baseline"].get(platform, "")
            prev_c = previous["current"].get(platform, "")
            adjacent_b = f"{trigram_jaccard(before, prev_b):.2f}" if before and prev_b else "—"
            adjacent_c = f"{trigram_jaccard(after, prev_c):.2f}" if after and prev_c else "—"
            note = f" _({_cell(row.error)})_" if row.error else ""
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
        "A floor, not a bill: `AIService` drops usage-less caption responses before",
        "they reach the counter, and a silent fallback from the single-call SD path to",
        "`generate_multi` is a second paid call that is not counted. The vision call is",
        "counted either way.",
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
    _fill_unused_env()
    images = _image_paths(folder, args.limit)
    if not images:
        raise SystemExit(f"no images ({', '.join(IMAGE_SUFFIXES)}) in {folder}")

    live_static = REPO_ROOT / STATIC_REL
    worktree = Path(tempfile.mkdtemp(prefix="caption-sample-baseline-")) / "tree"

    rows: list[Row] = []
    platforms: set[str] = set()
    history: dict[str, dict[str, list[str]]] = {"baseline": {}, "current": {}}
    try:
        baseline_static = _checkout_baseline_static(args.baseline, worktree)
        _refuse_if_prompts_are_overridden()
        if not _baseline_takes_history(worktree):
            raise SystemExit(
                f"{args.baseline} has no history parameter on create_multi_caption_pair_from_analysis: "
                "its half would be written without the history the current half gets, which makes the "
                "'before' look more repetitive than it was. Pick a baseline that takes history."
            )
        for image in images:
            row = Row(image=image.name)
            for variant, static_dir in (("baseline", baseline_static), ("current", live_static)):
                try:
                    if variant == "baseline":
                        captions, cost = _caption_once_at_baseline(image, worktree, static_dir, history[variant])
                    else:
                        captions, cost = asyncio.run(_caption_once(image, static_dir, history[variant]))
                    row.captions[variant] = captions
                    row.costs[variant] = cost
                    platforms |= set(captions)
                    # Each side accumulates its OWN history, so the #82 machinery
                    # sees what that side actually produced.
                    for platform, text in captions.items():
                        if text:
                            history[variant].setdefault(platform, []).insert(0, text)
                            del history[variant][platform][HISTORY_DEPTH:]
                except Exception as exc:  # one bad variant must not discard the other
                    row.error = f"{variant}: {type(exc).__name__}: {exc}"
                    if variant == "baseline" and not any(r.captions.get("baseline") for r in rows):
                        # The baseline half has never worked in this run, so it
                        # will not start working on image 2. Stopping here costs
                        # one current-side call instead of twenty.
                        raise SystemExit(
                            f"baseline half failed on the first image and produced nothing: {row.error}\n"
                            "Nothing to compare against — fix the baseline before paying for the rest."
                        ) from exc
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
