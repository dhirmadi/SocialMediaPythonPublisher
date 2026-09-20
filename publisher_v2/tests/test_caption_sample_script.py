"""#146: the offline parts of scripts/caption_sample.py.

The script's point is live model output, which only the account owner can
produce (their OpenAI key, their archived images). What can be tested without
that is everything around the two API calls: image selection, the baseline
worktree checkout, the cost accounting and the Markdown the owner will read.
"""

from __future__ import annotations

import importlib.util
import json
import os
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
    # The non-images sort FIRST, or the limit hides them and "images only" is
    # vacuous — a notes.txt would go to the vision API and nothing would fail.
    for name in ("b.jpg", "a.png", "c.jpeg", "0notes.txt", "1sidecar.md"):
        (tmp_path / name).write_bytes(b"x")

    assert [p.name for p in mod._image_paths(tmp_path, limit=99)] == ["a.png", "b.jpg", "c.jpeg"]
    assert [p.name for p in mod._image_paths(tmp_path, limit=2)] == ["a.png", "b.jpg"]  # sorted, capped


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
def _throwaway_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repo of our own, so a killed run cannot leave a worktree in the developer's.

    Two commits, and the working tree differs from the first: a test that reads
    the working tree, or ignores the commit it was given, would otherwise pass
    against the very thing it claims to catch.
    """
    repo = tmp_path / "repo"
    static = repo / "publisher_v2" / "src" / "publisher_v2" / "config" / "static"
    static.mkdir(parents=True)
    (static / "ai_prompts.yaml").write_text("caption:\n  system: baseline persona\n", encoding="utf-8")
    (static / "platform_limits.yaml").write_text("email: 240\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@e",
    }

    def _git(*argv: str) -> str:
        return subprocess.run(  # noqa: S603
            ["git", *argv],  # noqa: S607
            cwd=repo,
            check=True,
            capture_output=True,
            env=env,
            text=True,
        ).stdout

    _git("init", "-q")
    _git("add", "-A")
    _git("commit", "-qm", "baseline")
    baseline_sha = _git("rev-parse", "HEAD").strip()
    (static / "ai_prompts.yaml").write_text("caption:\n  system: current persona\n", encoding="utf-8")
    _git("add", "-A")
    _git("commit", "-qm", "current")
    return repo, baseline_sha


def test_the_baseline_worktree_yields_that_commits_static_config(tmp_path: Path, monkeypatch) -> None:
    """The 'before' side must come from the baseline commit, not the working tree."""
    mod = _module()
    repo, baseline_sha = _throwaway_repo(tmp_path)
    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    worktree = tmp_path / "tree"

    static = mod._checkout_baseline_static(baseline_sha, worktree)

    assert (static / "ai_prompts.yaml").read_text(encoding="utf-8").strip().endswith("baseline persona")
    assert (static / "platform_limits.yaml").is_file()
    subprocess.run(  # noqa: S603
        ["git", "worktree", "remove", "--force", str(worktree)],  # noqa: S607
        cwd=repo,
        check=False,
        capture_output=True,
    )


def test_the_baseline_half_runs_the_baseline_commits_own_code(tmp_path: Path, monkeypatch) -> None:
    """#146: the artefact answers "did #82 reduce repetition", and #82 is code.

    Running only the baseline YAML through today's ``services/ai.py`` would run
    both halves through the same similarity gate, history constraints and
    structure directives — a different question. The baseline half therefore
    runs in a subprocess with the worktree's own ``publisher_v2`` on PYTHONPATH.
    """
    mod = _module()
    worktree = tmp_path / "tree"
    src = worktree / "publisher_v2" / "src" / "publisher_v2"
    src.mkdir(parents=True)
    # A stand-in package: if the subprocess imported the working tree's code
    # instead of this one, the marker below would not come back.
    (src / "__init__.py").write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["pythonpath"] = kwargs["env"]["PYTHONPATH"]
        captured["cwd"] = kwargs["cwd"]
        payload = json.loads(argv[-1])
        captured["payload"] = payload
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "captions": {"telegram": "baseline text"},
                    "cost": {"calls": 2, "prompt_tokens": 10, "completion_tokens": 3},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    captions, cost = mod._caption_once_at_baseline(
        Path("/images/a.jpg"), worktree, worktree / "static", {"telegram": ["older"]}
    )

    assert captions == {"telegram": "baseline text"}
    assert (cost.calls, cost.prompt_tokens, cost.completion_tokens) == (2, 10, 3)
    assert captured["pythonpath"] == str(worktree / "publisher_v2" / "src")
    assert captured["cwd"] == str(worktree)
    assert captured["payload"]["history"] == {"telegram": ["older"]}


def test_the_documented_invocation_supplies_every_required_variable(monkeypatch) -> None:
    """#146: the documented command used to fail three times over on unused secrets."""
    mod = _module()
    for name in (*mod._UNUSED_ENV_PLACEHOLDERS, "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    mod._fill_unused_env()

    for name in mod._UNUSED_ENV_PLACEHOLDERS:
        assert os.environ.get(name), f"{name} left unset"


def test_it_refuses_to_start_without_a_key(monkeypatch) -> None:
    mod = _module()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        mod._fill_unused_env()


def test_the_baseline_commits_yaml_still_loads(tmp_path: Path) -> None:
    """Refutes the cross-PR MAJOR: #152 no longer rejects the 5c086e6 config.

    That review was written while #152 raised a ValidationError on a
    `platform_captions.*.examples` key, which would have failed every baseline
    half while the current half still paid for its call. #152 now strips the key
    with a warning — the same reason the app survives a stale
    PV2_STATIC_CONFIG_DIR — so the baseline YAML loads. Asserted against the
    real commit rather than argued.
    """
    import yaml

    from publisher_v2.config.static_loader import load_static_config

    baseline_yaml = subprocess.run(  # noqa: S603
        ["git", "show", "5c086e6:publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml"],  # noqa: S607
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "examples:" in baseline_yaml, "the baseline is supposed to carry the static examples"
    (tmp_path / "ai_prompts.yaml").write_text(baseline_yaml, encoding="utf-8")

    config = load_static_config(str(tmp_path))

    assert config.ai_prompts.platform_captions
    shipped = yaml.safe_load(baseline_yaml)["platform_captions"]
    for name, style in config.ai_prompts.platform_captions.items():
        if name in shipped:
            assert style.max_length == shipped[name]["max_length"]
            assert not getattr(style, "examples", None), "examples must be stripped, not kept"


def test_run_sends_the_baseline_to_the_baseline_code_and_feeds_each_side_its_own_history(
    tmp_path: Path, monkeypatch
) -> None:
    """The wiring, not the helpers: three earlier fixes all lived inside `run`.

    Mutating `run` to call the in-process path for both halves, to skip the
    placeholder fill, or to drop the history left the helper tests green.
    """
    mod = _module()
    images = tmp_path / "images"
    images.mkdir()
    for name in ("a.jpg", "b.jpg"):
        (images / name).write_bytes(b"\xff\xd8\xff")
    calls: dict[str, list] = {"baseline": [], "current": [], "filled": []}

    def _fake_checkout(commit: str, into: Path) -> Path:
        (into / "static").mkdir(parents=True)
        return into / "static"

    def _fake_baseline(image, worktree, static_dir, history):
        calls["baseline"].append((image.name, json.dumps(history, sort_keys=True)))
        return {"telegram": f"baseline {image.name}"}, mod.Cost(calls=1)

    async def _fake_current(image, static_dir, history=None):
        calls["current"].append((image.name, json.dumps(history or {}, sort_keys=True)))
        return {"telegram": f"current {image.name}"}, mod.Cost(calls=1)

    monkeypatch.setattr(mod, "_checkout_baseline_static", _fake_checkout)
    monkeypatch.setattr(mod, "_caption_once_at_baseline", _fake_baseline)
    monkeypatch.setattr(mod, "_caption_once", _fake_current)
    monkeypatch.setattr(mod, "_refuse_if_prompts_are_overridden", lambda: None)
    monkeypatch.setattr(mod, "_fill_unused_env", lambda: calls["filled"].append(True))
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    out = tmp_path / "report.md"

    mod.run(SimpleNamespace(images=str(images), limit=10, baseline="5c086e6", out=str(out)))

    assert calls["filled"], "the documented invocation depends on the placeholder fill"
    # The baseline half went to the baseline code, once per image.
    assert [name for name, _ in calls["baseline"]] == ["a.jpg", "b.jpg"]
    assert [name for name, _ in calls["current"]] == ["a.jpg", "b.jpg"]
    # Each side accumulated its OWN captions as history for the second image.
    assert calls["baseline"][0][1] == "{}"
    assert json.loads(calls["baseline"][1][1]) == {"telegram": ["baseline a.jpg"]}
    assert json.loads(calls["current"][1][1]) == {"telegram": ["current a.jpg"]}
    report = out.read_text(encoding="utf-8")
    assert "baseline a.jpg" in report and "current b.jpg" in report


def _baseline_available() -> bool:
    return (
        subprocess.run(  # noqa: S603
            ["git", "cat-file", "-e", "5c086e6^{commit}"],  # noqa: S607
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


@pytest.mark.skipif(not _baseline_available(), reason="baseline commit not in this clone")
def test_the_worker_runs_against_the_real_baseline_commit(tmp_path: Path) -> None:
    """#146: the baseline half must work at the commit the artefact names.

    The worker was written against today's API and died twice at 5c086e6 before
    any comparison was possible: `AIService.aclose` did not exist yet (added in
    989f9e1) and `analyze` rejected bytes (byte input arrived in 6c0641d). Both
    failures were raised inside the subprocess, so every row came back an error
    string — after paying for the whole current-side run.

    This drives the real worker against a real extraction of that commit. It
    stops at the OpenAI call, which is the first thing that needs a key: getting
    that far means the imports, the config, the analyzer entry point and the
    teardown all match the baseline's own API.
    """
    mod = _module()
    tree = tmp_path / "baseline"
    tree.mkdir()
    archive = subprocess.run(  # noqa: S603
        ["git", "archive", "5c086e6"],  # noqa: S607
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)  # noqa: S603, S607
    image = tmp_path / "img.jpg"
    image.write_bytes(bytes.fromhex("ffd8ffdb") + b"x" * 64)
    static = tree / "publisher_v2" / "src" / "publisher_v2" / "config" / "static"

    assert mod._baseline_analyze_wants_url(tree) is True, "this baseline predates byte input"

    os.environ.setdefault("OPENAI_API_KEY", "sk-not-a-real-key")
    mod._fill_unused_env()
    with pytest.raises(RuntimeError) as excinfo:
        mod._caption_once_at_baseline(image, tree, static, {"telegram": ["older"]})

    message = str(excinfo.value)
    # The failure must be the missing key, not a mismatch with the baseline API.
    assert "Incorrect API key" in message or "api_key" in message.lower(), message
    for regression in ("aclose", "Byte input not supported", "UnsupportedProtocol"):
        assert regression not in message, f"worker does not match the baseline API: {message}"


def test_a_failing_worker_reports_only_its_last_line(monkeypatch, tmp_path: Path) -> None:
    """The failure path that fires on every image when the baseline is wrong.

    It was untested, and without the returncode check the next line raises
    IndexError on empty stdout instead of showing what went wrong. The message
    carries one line, not the traceback: row.error is written into a Markdown
    file bound for docs_v2, and a traceback from a process whose environment
    holds the API key is not a redaction boundary.
    """
    mod = _module()
    secret_ish = "Traceback (most recent call last):\n  File x, line 1\nValueError: boom | with a pipe"

    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout="", stderr=secret_ish),
    )

    with pytest.raises(RuntimeError) as excinfo:
        mod._caption_once_at_baseline(tmp_path / "a.jpg", tmp_path, tmp_path, None)

    message = str(excinfo.value)
    assert "ValueError: boom" in message
    assert "Traceback" not in message, "the whole traceback must not reach the report"
    assert "\n" not in message


def test_a_dead_baseline_stops_the_run_instead_of_billing_every_image(tmp_path: Path, monkeypatch) -> None:
    """#146: with the baseline half broken there is nothing to compare against."""
    mod = _module()
    images = tmp_path / "images"
    images.mkdir()
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        (images / name).write_bytes(b"\xff\xd8\xff")
    current_calls: list[str] = []

    async def _fake_current(image, static_dir, history=None):
        current_calls.append(image.name)
        return {"telegram": "current"}, mod.Cost(calls=1)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("baseline worker failed: AttributeError: no aclose")

    monkeypatch.setattr(mod, "_checkout_baseline_static", lambda commit, into: into)
    monkeypatch.setattr(mod, "_caption_once_at_baseline", _boom)
    monkeypatch.setattr(mod, "_caption_once", _fake_current)
    monkeypatch.setattr(mod, "_refuse_if_prompts_are_overridden", lambda: None)
    monkeypatch.setattr(mod, "_fill_unused_env", lambda: None)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))

    with pytest.raises(SystemExit, match="baseline half failed"):
        mod.run(SimpleNamespace(images=str(images), limit=10, baseline="5c086e6", out=str(tmp_path / "r.md")))

    # The baseline half runs first, so the abort lands before the current side is
    # called at all: zero paid calls, not one per remaining image.
    assert current_calls == [], "images were paid for with nothing to compare them to"
