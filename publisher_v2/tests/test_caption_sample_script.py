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
    """PUB-049 AC7: the trigram-only Delta column is retired for the harness metrics.

    The per-row columns are now the two harness numbers, per side: whether the
    caption trips the tells lexicon, and its TF-IDF bigram cosine against the
    captions already emitted for earlier images on that same side. With a single
    row there is no history yet, so both cosine cells read as unavailable.
    """
    mod = _module()
    row = mod.Row(image="img.jpg")
    row.captions = {
        "baseline": {"telegram": "This isn't just rope, it is trust", "email": "A quiet evening"},
        "current": {"telegram": "Rope marks on warm skin", "email": "Knots and patience, slowly"},
    }
    row.costs = {"baseline": mod.Cost(calls=2, prompt_tokens=100, completion_tokens=20)}

    table = mod._render([row], "5c086e6", ["telegram", "email"])

    assert "Baseline: `5c086e6`" in table
    assert "One asymmetry" in table, "the vision-payload difference must be disclosed"

    # The retired column and the metric behind it are gone.
    assert "| Delta |" not in table
    assert "trigram" not in table.lower()

    assert (
        "| Image | Platform | Baseline caption | Current caption | Tells (baseline) | Tells (current) | "
        "Cosine (baseline) | Cosine (current) |"
    ) in table

    # "isn't just" is a tells-lexicon phrase; the current telegram caption is not.
    assert (
        "| `img.jpg` | telegram | This isn't just rope, it is trust | Rope marks on warm skin | 1.00 | 0.00 | — | — |"
    ) in table
    assert ("| `img.jpg` | email | A quiet evening | Knots and patience, slowly | 0.00 | 0.00 | — | — |") in table
    assert "| `img.jpg` | baseline | 2 | 100 | 20 |" in table


def test_similarity_to_the_previous_image_is_reported_per_variant() -> None:
    """PUB-049 AC7: the summary section is now the harness deltas, not the trigram mean.

    #146 still asks for repetitiveness across images; the number answering it is
    now the tells rate and the TF-IDF bigram cosine to the captions already
    emitted on that side, reported per platform with the baseline-to-current
    delta.
    """
    mod = _module()
    rows = []
    for name, baseline, current in (
        ("a.jpg", "This isn't just the same opener every time", "a quiet first line"),
        ("b.jpg", "This isn't just the same opener every time", "rope, and then patience"),
    ):
        row = mod.Row(image=name)
        row.captions = {"baseline": {"telegram": baseline}, "current": {"telegram": current}}
        rows.append(row)

    table = mod._render(rows, "5c086e6", ["telegram"])

    assert "Mean similarity to the previous image" not in table, "the trigram-only section is retired"
    assert "## Harness deltas (baseline vs current, lower = less repetitive)" in table
    assert (
        "| Platform | Tells rate (baseline) | Tells rate (current) | Tells Δ | "
        "Mean cosine (baseline) | Mean cosine (current) | Cosine Δ |"
    ) in table

    # Every baseline caption trips the lexicon; no current caption does.
    summary = [line for line in table.splitlines() if line.startswith("| telegram |")]
    assert len(summary) == 1, table
    cells = [cell.strip() for cell in summary[0].strip("|").split("|")]
    assert cells[:4] == ["telegram", "1.00", "0.00", "-1.00"]

    # The baseline repeats itself verbatim, so it is far closer to its own history.
    mean_cosine_baseline, mean_cosine_current = float(cells[4]), float(cells[5])
    assert mean_cosine_baseline > mean_cosine_current
    assert float(cells[6]) == pytest.approx(mean_cosine_current - mean_cosine_baseline, abs=0.005)


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
    # A real row.error is a line of subprocess stderr, which can carry both.
    row = mod.Row(image="broken.jpg", error="RuntimeError: vision | exploded\nat line 2")

    table = mod._render([row], "5c086e6", ["telegram"])

    assert "_RuntimeError: vision \\| exploded<br>at line 2_" in table, table
    error_row = next(line for line in table.splitlines() if "broken.jpg" in line)
    # Nine cell separators (PUB-049 AC7 widened the table from seven columns to
    # eight); the error's own pipe is escaped, so it is not one of them.
    assert error_row.count("|") - error_row.count("\\|") == 9, f"the error broke the table: {error_row}"
    assert "\n" not in error_row.strip()


def test_pipe_characters_in_a_caption_do_not_break_the_table() -> None:
    mod = _module()
    row = mod.Row(image="img.jpg")
    row.captions = {"baseline": {"telegram": "a | b"}, "current": {"telegram": "c | d"}}

    table = mod._render([row], "5c086e6", ["telegram"])

    body = [line for line in table.splitlines() if line.startswith("| `img.jpg`")][0]
    unescaped = body.replace("\\|", "")
    assert unescaped.count("|") == 9, body  # 8 columns (PUB-049 AC7); pipes inside captions are escaped


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
                    "history_used": True,
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
    # _fill_unused_env writes os.environ directly, and delenv records no undo for
    # a name that was already absent — so hand monkeypatch something to restore.
    for name in mod._UNUSED_ENV_PLACEHOLDERS:
        monkeypatch.setenv(name, "")

    mod._fill_unused_env()

    for name in mod._UNUSED_ENV_PLACEHOLDERS:
        assert os.environ.get(name), f"{name} left unset"


def test_it_refuses_to_start_without_a_key(monkeypatch) -> None:
    mod = _module()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # _fill_unused_env writes os.environ before it raises, and delenv records no
    # undo for a name that was already absent — so the placeholders would leak
    # into the rest of a random-ordered suite. "" counts as unset to it.
    for name in mod._UNUSED_ENV_PLACEHOLDERS:
        monkeypatch.setenv(name, "")

    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        mod._fill_unused_env()


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


@pytest.mark.skipif(not _baseline_available(), reason="baseline commit not in this clone")
def test_the_worker_runs_against_the_real_baseline_commit(tmp_path: Path, monkeypatch) -> None:
    """#146: the baseline half must work at the commit the artefact names.

    The worker was written against today's API and died twice at 5c086e6 before
    any comparison was possible: `AIService.aclose` did not exist yet (added in
    989f9e1) and `analyze` rejected bytes (byte input arrived in 6c0641d). Both
    failures were raised inside the subprocess, so every row came back an error
    string — after paying for the whole current-side run.

    This drives the real worker against a real extraction of that commit, with
    the API pointed at a closed port: the run must fail at the *network*, which
    means the imports, the config, the analyzer entry point and the teardown all
    matched the baseline's own API. Pointing at the real endpoint would bill
    whoever has a working key in their environment — the operator of this very
    script — on every pytest run.
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

    # Nothing may reach OpenAI, and nothing may leak into the rest of the session.
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    for name, value in mod._UNUSED_ENV_PLACEHOLDERS.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError) as excinfo:
        mod._caption_once_at_baseline(image, tree, static, {"telegram": ["older"]})

    message = str(excinfo.value)
    # Reaching the network means every earlier step matched the baseline's API.
    # Only the connection error: the generic AIServiceError wrapper would also
    # match a real-endpoint 401, so it would not notice the base-URL override
    # silently ceasing to work.
    assert "Connection error" in message, message
    for regression in ("aclose", "Byte input not supported", "UnsupportedProtocol"):
        assert regression not in message, f"worker does not match the baseline API: {message}"


def test_a_baseline_that_ignored_the_history_is_refused(tmp_path: Path, monkeypatch) -> None:
    """A history-free baseline writes a MORE repetitive "before", flattering #82.

    The worker reports whether it actually used the history it was given; that
    signal used to be discarded, so such a run would have been reported as a
    clean comparison.
    """
    mod = _module()

    def _fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "captions": {"telegram": "baseline text"},
                    "cost": {"calls": 2, "prompt_tokens": 10, "completion_tokens": 3},
                    "history_used": False,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="without history"):
        mod._caption_once_at_baseline(tmp_path / "a.jpg", tmp_path, tmp_path, {"telegram": ["older"]})

    # With no history asked for, there is nothing to ignore.
    captions, _cost = mod._caption_once_at_baseline(tmp_path / "a.jpg", tmp_path, tmp_path, None)
    assert captions == {"telegram": "baseline text"}


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


def _stub_publisher_v2(root: Path, *, takes_history: bool) -> Path:
    """A four-name stand-in for publisher_v2, so the worker runs with no key and no network."""
    pkg = root / "publisher_v2"
    (pkg / "config").mkdir(parents=True)
    (pkg / "core").mkdir()
    (pkg / "services").mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "config" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "services" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "config" / "loader.py").write_text(
        "from types import SimpleNamespace\n"
        "def load_application_config():\n"
        "    return SimpleNamespace(openai=SimpleNamespace(api_key='x'))\n",
        encoding="utf-8",
    )
    (pkg / "config" / "static_loader.py").write_text(
        "def get_static_config():\n    return None\nget_static_config.cache_clear = lambda: None\n",
        encoding="utf-8",
    )
    (pkg / "core" / "models.py").write_text(
        "class CaptionSpec:\n"
        "    @staticmethod\n"
        "    def for_platforms(config):\n"
        "        return {'telegram': object()}\n",
        encoding="utf-8",
    )
    history_param = ", history=None" if takes_history else ""
    (pkg / "services" / "ai.py").write_text(
        "class _Analyzer:\n"
        "    def __init__(self, *a, **k):\n        pass\n"
        "    async def analyze(self, subject):\n"
        "        return object(), None\n"
        "class VisionAnalyzerOpenAI(_Analyzer):\n    pass\n"
        "class CaptionGeneratorOpenAI(_Analyzer):\n    pass\n"
        "class AIService:\n"
        "    def __init__(self, analyzer, generator):\n        self.analyzer = analyzer\n"
        f"    async def create_multi_caption_pair_from_analysis(self, analysis, specs{history_param}):\n"
        "        return {'telegram': 'stub'}, None, []\n",
        encoding="utf-8",
    )
    return pkg.parent


class TestTheWorkerReportsWhetherItUsedTheHistory:
    """#146: a worker that claims it used history when it did not makes the
    caller-side refusal a no-op, and produces a flattering artefact silently.

    The caller cannot see that; only the worker's own JSON can. It imports
    exactly four names, so a stub package pins both directions with no key and
    no network.
    """

    @staticmethod
    def _run_worker(mod, src: Path, history: dict) -> dict:
        payload = {
            "image": __file__,  # any readable file: the stub analyzer ignores it
            "static_dir": str(src),
            "history": history,
            "analyze_wants_url": False,
        }
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-c", mod._BASELINE_WORKER, json.dumps(payload)],
            cwd=str(src),
            env={**os.environ, "PYTHONPATH": str(src)},
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr[-800:]
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_a_baseline_without_the_parameter_reports_false(self, tmp_path: Path) -> None:
        mod = _module()
        src = _stub_publisher_v2(tmp_path / "old", takes_history=False)

        result = self._run_worker(mod, src, {"telegram": ["older"]})

        assert result["history_used"] is False, "claiming history it did not use flatters the current side"
        assert result["captions"] == {"telegram": "stub"}

    def test_a_baseline_with_the_parameter_reports_true(self, tmp_path: Path) -> None:
        mod = _module()
        src = _stub_publisher_v2(tmp_path / "new", takes_history=True)

        result = self._run_worker(mod, src, {"telegram": ["older"]})

        assert result["history_used"] is True
        assert result["captions"] == {"telegram": "stub"}, "the real publisher_v2 was imported, not the stub"

    def test_no_history_asked_for_is_not_reported_as_used(self, tmp_path: Path) -> None:
        mod = _module()
        src = _stub_publisher_v2(tmp_path / "new2", takes_history=True)

        result = self._run_worker(mod, src, {})

        assert result["history_used"] is False
        assert result["captions"] == {"telegram": "stub"}, "the real publisher_v2 was imported, not the stub"


def test_a_baseline_without_history_support_is_refused_before_any_paid_call(tmp_path: Path, monkeypatch) -> None:
    """#146: the runtime refusal cannot fire on image 1, which has no history yet.

    Left to the runtime check alone, a history-ignoring baseline bills both
    halves of every image and only image 1 yields a comparable row.
    """
    mod = _module()
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.jpg").write_bytes(b"\xff\xd8\xff")
    tree = tmp_path / "tree"
    src = _stub_publisher_v2(tree, takes_history=False)
    paid: list[str] = []

    async def _fake_current(image, static_dir, history=None):
        paid.append(image.name)
        return {"telegram": "current"}, mod.Cost(calls=1)

    def _fake_checkout(commit: str, into: Path) -> Path:
        # run() creates its own temp worktree, so the stub must land where the
        # check will look: <worktree>/publisher_v2/src/publisher_v2/services/ai.py
        target = into / "publisher_v2" / "src" / "publisher_v2" / "services"
        target.mkdir(parents=True, exist_ok=True)
        (target / "ai.py").write_text(
            (src / "publisher_v2" / "services" / "ai.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        static = into / "static"
        static.mkdir(exist_ok=True)
        return static

    monkeypatch.setattr(mod, "_checkout_baseline_static", _fake_checkout)
    monkeypatch.setattr(mod, "_caption_once", _fake_current)

    def _paid_baseline(*_args, **_kwargs):
        paid.append("baseline")
        return {}, mod.Cost()

    monkeypatch.setattr(mod, "_caption_once_at_baseline", _paid_baseline)
    monkeypatch.setattr(mod, "_refuse_if_prompts_are_overridden", lambda: None)
    monkeypatch.setattr(mod, "_fill_unused_env", lambda: None)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))

    with pytest.raises(SystemExit, match="no history parameter"):
        mod.run(SimpleNamespace(images=str(images), limit=10, baseline="old", out=str(tmp_path / "r.md")))

    assert paid == [], "the run paid for images it could not compare"


def test_a_baseline_with_history_support_is_not_refused(tmp_path: Path) -> None:
    mod = _module()
    src = _stub_publisher_v2(tmp_path / "new3", takes_history=True)

    # _baseline_takes_history reads <worktree>/publisher_v2/src/publisher_v2/services/ai.py
    worktree = tmp_path / "wt"
    target = worktree / "publisher_v2" / "src" / "publisher_v2" / "services"
    target.mkdir(parents=True)
    (target / "ai.py").write_text(
        (src / "publisher_v2" / "services" / "ai.py").read_text(encoding="utf-8"), encoding="utf-8"
    )

    assert mod._baseline_takes_history(worktree) is True


class TestTheHistoryProbeReadsTheSignature:
    """#146: a false positive here re-opens the billing hole it exists to close.

    Once image 1 succeeds the run's abort condition no longer holds, so a
    baseline wrongly judged history-capable bills both halves of every image
    while the runtime refusal only marks rows as errors. A substring match on
    the source text says yes to `history_by_platform` and to a `# history`
    comment; the parameter list is parsed instead.
    """

    @staticmethod
    def _tree(tmp_path: Path, signature: str) -> Path:
        tree = tmp_path / "wt"
        target = tree / "publisher_v2" / "src" / "publisher_v2" / "services"
        target.mkdir(parents=True)
        (target / "ai.py").write_text(
            "class AIService:\n"
            f"    async def create_multi_caption_pair_from_analysis({signature}):\n"
            "        return {}, None, []\n",
            encoding="utf-8",
        )
        return tree

    def test_a_history_parameter_is_found(self, tmp_path: Path) -> None:
        mod = _module()
        assert mod._baseline_takes_history(self._tree(tmp_path, "self, analysis, specs, history=None")) is True

    def test_a_multi_line_signature_is_read(self, tmp_path: Path) -> None:
        mod = _module()
        tree = self._tree(tmp_path, "\n        self,\n        analysis,\n        specs,\n        history=None,\n    ")
        assert mod._baseline_takes_history(tree) is True

    def test_a_similar_name_is_not_mistaken_for_it(self, tmp_path: Path) -> None:
        mod = _module()
        assert (
            mod._baseline_takes_history(self._tree(tmp_path, "self, analysis, specs, history_by_platform=None"))
            is False
        )

    def test_a_comment_mentioning_history_is_not_a_parameter(self, tmp_path: Path) -> None:
        mod = _module()
        # The comment must sit inside a multi-line list, or the closing paren
        # lands inside it and the file does not parse at all.
        tree = self._tree(tmp_path, "\n        self, analysis, specs,  # history goes here one day\n    ")
        assert mod._baseline_takes_history(tree) is False

    def test_a_default_containing_a_bracket_does_not_truncate_the_list(self, tmp_path: Path) -> None:
        mod = _module()
        tree = self._tree(tmp_path, "self, analysis, specs, hook=(lambda: None), history=None")
        assert mod._baseline_takes_history(tree) is True

    def test_an_unreadable_tree_fails_open(self, tmp_path: Path) -> None:
        """The worker then dies on image 1 and the run's own abort stops it there."""
        mod = _module()
        assert mod._baseline_takes_history(tmp_path / "nothing") is True
