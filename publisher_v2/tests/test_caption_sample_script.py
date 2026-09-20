"""#146: the offline parts of scripts/caption_sample.py.

The script's point is live model output, which only the account owner can
produce (their OpenAI key, their archived images). What can be tested without
that is everything around the two API calls: image selection, the baseline
worktree checkout, the cost accounting and the Markdown the owner will read.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("caption_sample", REPO_ROOT / "scripts" / "caption_sample.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["caption_sample"] = module
    spec.loader.exec_module(module)
    return module


def test_only_images_are_sampled_and_the_limit_is_honoured(tmp_path: Path) -> None:
    mod = _module()
    for name in ("b.jpg", "a.png", "c.jpeg", "notes.txt", "sidecar.md"):
        (tmp_path / name).write_bytes(b"x")

    picked = mod._image_paths(tmp_path, limit=2)

    assert [p.name for p in picked] == ["a.png", "b.jpg"]  # sorted, images only, capped


def test_cost_accounting_sums_calls_and_tokens() -> None:
    mod = _module()
    cost = mod.Cost()

    cost.add([SimpleNamespace(prompt_tokens=10, completion_tokens=4), None])
    cost.add([SimpleNamespace(prompt_tokens=1, completion_tokens=2)])

    # A call with no usage payload still cost money, so it is counted.
    assert (cost.calls, cost.prompt_tokens, cost.completion_tokens, cost.total_tokens) == (3, 11, 6, 17)


def test_the_table_pairs_each_platform_and_scores_similarity() -> None:
    mod = _module()
    row = mod.Row(image="img.jpg")
    row.captions = {
        "baseline": {"telegram": "Rope marks on warm skin", "email": "A quiet evening"},
        "current": {"telegram": "Rope marks on warm skin", "email": "Knots and patience, slowly"},
    }
    row.costs = {"baseline": mod.Cost(calls=2, prompt_tokens=100, completion_tokens=20)}

    table = mod._render([row], "5c086e6", ["telegram", "email"])

    assert "Baseline prompt configuration: `5c086e6`" in table
    assert "| `img.jpg` | telegram | Rope marks on warm skin | Rope marks on warm skin | 1.00 |" in table.replace(
        " | — | — |", " |"
    )
    assert "| `img.jpg` | email | A quiet evening | Knots and patience, slowly | 0.00 |" in table.replace(
        " | — | — |", " |"
    )
    assert "| `img.jpg` | baseline | 2 | 100 | 20 |" in table


def test_similarity_to_the_previous_image_is_reported_per_variant() -> None:
    """#146 asks for repetitiveness across images, which is the #82 claim under test."""
    mod = _module()
    rows = []
    for name, baseline, current in (
        ("a.jpg", "the same opener every time", "a quiet first line"),
        ("b.jpg", "the same opener every time", "rope, and then patience"),
    ):
        row = mod.Row(image=name)
        row.captions = {"baseline": {"telegram": baseline}, "current": {"telegram": current}}
        rows.append(row)

    table = mod._render(rows, "5c086e6", ["telegram"])

    assert "Mean similarity to the previous image" in table
    # The baseline repeats itself verbatim; the current captions do not.
    assert "| telegram | 1.00 | 0.00 |" in table


def test_a_newline_in_a_caption_cannot_break_the_table() -> None:
    mod = _module()
    row = mod.Row(image="img.jpg")
    row.captions = {"baseline": {"telegram": "first line\nsecond line"}, "current": {"telegram": "one line"}}

    table = mod._render([row], "5c086e6", ["telegram"])

    body = [line for line in table.splitlines() if line.startswith("| `img.jpg`")]
    assert len(body) == 1, table
    assert "<br>" in body[0]


def test_a_half_that_succeeded_is_still_reported() -> None:
    """The baseline call is paid for even when the current one fails — show it."""
    mod = _module()
    row = mod.Row(image="img.jpg", error="current: AIServiceError: boom")
    row.captions = {"baseline": {"telegram": "a caption we paid for"}}

    table = mod._render([row], "5c086e6", ["telegram"])

    assert "a caption we paid for" in table
    assert "current: AIServiceError: boom" in table


def test_a_failed_image_is_reported_not_dropped() -> None:
    mod = _module()
    row = mod.Row(image="broken.jpg", error="RuntimeError: vision exploded")

    table = mod._render([row], "5c086e6", ["telegram"])

    assert "_RuntimeError: vision exploded_" in table


def test_pipe_characters_in_a_caption_do_not_break_the_table() -> None:
    mod = _module()
    row = mod.Row(image="img.jpg")
    row.captions = {"baseline": {"telegram": "a | b"}, "current": {"telegram": "c | d"}}

    table = mod._render([row], "5c086e6", ["telegram"])

    body = [line for line in table.splitlines() if line.startswith("| `img.jpg`")][0]
    unescaped = body.replace("\\|", "")
    assert unescaped.count("|") == 8, body  # 7 columns; the pipes inside captions are escaped


@pytest.mark.skipif(
    subprocess.run(  # noqa: S603
        ["git", "rev-parse", "--verify", "5c086e6"],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
    ).returncode
    != 0,
    reason="baseline commit not present in this clone",
)
def test_the_baseline_worktree_yields_that_commits_static_config(tmp_path: Path) -> None:
    """The 'before' side must come from the baseline commit, not the working tree."""
    mod = _module()
    worktree = tmp_path / "tree"
    try:
        static = mod._checkout_baseline_static("5c086e6", worktree)
        assert (static / "ai_prompts.yaml").is_file()
        assert (static / "platform_limits.yaml").is_file()
    finally:
        subprocess.run(  # noqa: S603
            ["git", "worktree", "remove", "--force", str(worktree)],  # noqa: S607
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
