"""Suite-wide hygiene guards (PUB-084).

These tests check properties of the test suite itself: that the autouse setup isolates
process-wide state for every test, and that per-file copies of that isolation do not creep back.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from publisher_v2.utils import state
from publisher_v2.web import auth as web_auth

TESTS_ROOT = Path(__file__).resolve().parent
THIS_FILE = Path(__file__).resolve()

_XDG_SETTERS = re.compile(
    r"""setenv\(\s*["']XDG_CACHE_HOME["']"""
    r"""|setitem\(\s*os\.environ\s*,\s*["']XDG_CACHE_HOME["']"""
    r"""|os\.environ\[\s*["']XDG_CACHE_HOME["']\s*\]\s*="""
    r"""|["']XDG_CACHE_HOME["']\s*:"""
)
_BYPASS_DEDUP = re.compile(r"\bbypass_dedup\b")
# Isolation-only no-op patches of the posted-state helpers, e.g.
#   monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
#   monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
# Behavioural patches (non-empty sets, recorders such as ``lambda v: saved.append(v)``) are allowed.
_NOOP_POSTED_STATE_PATCH = re.compile(
    r"""setattr\(\s*[^()]*?\b(?:load|save)_posted_\w+["']?\s*,\s*lambda[^:()]*:\s*(?:set\(\s*\)|None)\s*,?\s*\)"""
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("run", ["first", "second"])
def test_posted_state_cache_is_isolated_per_test(tmp_path_factory: pytest.TempPathFactory, run: str) -> None:
    """AC1: autouse setup points XDG_CACHE_HOME at a per-test temp dir; utils.state resolves there.

    Runs twice and records a posted hash each time: if the dir were shared (session-scoped),
    whichever run goes second would find the other's posted.json instead of an empty dir.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    assert xdg, "autouse test setup must set XDG_CACHE_HOME for every test"
    assert Path(xdg).name.startswith("xdg-cache"), f"XDG_CACHE_HOME={xdg!r} is not the autouse per-test dir"
    assert list(Path(xdg).iterdir()) == [], f"XDG_CACHE_HOME={xdg!r} is not empty at test start ({run} run)"
    assert state.load_posted_hashes() == set()

    basetemp = tmp_path_factory.getbasetemp()
    home = Path.home()
    assert _is_within(Path(xdg), basetemp), f"XDG_CACHE_HOME={xdg!r} is not inside pytest's temp dir {basetemp}"
    assert not _is_within(Path(xdg), home / ".cache"), f"XDG_CACHE_HOME={xdg!r} points at the real ~/.cache"

    cache = state._cache_path()
    assert _is_within(cache, Path(xdg)), f"posted-state cache {cache} does not resolve under {xdg}"
    assert not _is_within(cache, home / ".cache"), f"posted-state cache {cache} resolves under the real home"

    state.save_posted_hash(f"hygiene-{run}")
    assert state.load_posted_hashes() == {f"hygiene-{run}"}


def test_no_per_file_posted_state_isolation() -> None:
    """AC2: no per-file XDG_CACHE_HOME, bypass_dedup fixture, or no-op posted-state patch exists."""
    xdg_offenders: list[str] = []
    bypass_offenders: list[str] = []
    noop_patch_offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if path.resolve() == THIS_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(TESTS_ROOT))
        if path.name != "conftest.py":
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _XDG_SETTERS.search(line):
                    xdg_offenders.append(f"{rel}:{lineno}")
        if _BYPASS_DEDUP.search(text):
            bypass_offenders.append(rel)
        for match in _NOOP_POSTED_STATE_PATCH.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            noop_patch_offenders.append(f"{rel}:{lineno}")

    assert not xdg_offenders, (
        "per-file XDG_CACHE_HOME isolation is redundant with the autouse setup; remove it from: "
        + ", ".join(xdg_offenders)
    )
    assert not bypass_offenders, "bypass_dedup must not be defined or used; found in: " + ", ".join(bypass_offenders)
    assert not noop_patch_offenders, (
        "no-op load_posted_*/save_posted_* patches are redundant with the autouse per-test XDG cache; "
        "remove them from: " + ", ".join(noop_patch_offenders)
    )


# --- PUB-084 wave 2 (#297): shared OpenAI fake, no AIService subclasses, live fixtures, one config builder ---

# The one module allowed to build OpenAI responses, patch AsyncOpenAI and construct ApplicationConfig directly.
_SHARED_FAKES_MODULE = "caption_pipeline_fakes.py"
# Files that touch AsyncOpenAI for a reason other than faking it.
_ASYNC_OPENAI_PATCH_ALLOWLIST = {
    # Tripwire: proves the offline eval script never builds an OpenAI client at all (patched to raise).
    "test_caption_eval_script.py",
}
# Root test files that test the ApplicationConfig model itself (its validators and defaults), so they
# must construct it directly rather than through make_app_config.
_APPLICATION_CONFIG_MODEL_TESTS: dict[str, str] = {
    "test_config_managed.py": "tests ApplicationConfig's exactly-one-storage-provider validator itself",
}


def _w2_test_sources() -> list[tuple[str, str]]:
    """(path relative to tests/, source) for every Python file under tests/, this file excluded."""
    out = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if path.resolve() == THIS_FILE or "__pycache__" in path.parts:
            continue
        out.append((path.relative_to(TESTS_ROOT).as_posix(), path.read_text(encoding="utf-8")))
    return out


def _w2_dotted(node: object) -> str:
    import ast

    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _w2_openai_fake_offences(rel: str, source: str) -> list[str]:
    """Hand-rolled OpenAI response chains and hand-written AsyncOpenAI patches in one file."""
    import ast

    tree = ast.parse(source)
    found: list[str] = []
    chain_words = {"choices", "completions"}
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        # SimpleNamespace(choices=[...]) / SimpleNamespace(completions=...)
        if isinstance(node, ast.keyword) and node.arg in chain_words:
            found.append(f"{rel}:{node.value.lineno} {node.arg}= response/client chain")
        # type("Chat", (), {"completions": ...}) / {"choices": [...]}
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value in chain_words:
                    found.append(f"{rel}:{line} {{{key.value!r}: ...}} response/client chain")
        # self.choices = ... / mock.chat.completions.create = AsyncMock(...)
        # ai_module.AsyncOpenAI = FakeClient (a plain assignment patch, never undone)
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Attribute):
                    continue
                if chain_words & set(_w2_dotted(target).split(".")):
                    found.append(f"{rel}:{line} {_w2_dotted(target)} = ... response/client chain")
                elif target.attr == "AsyncOpenAI" and rel not in _ASYNC_OPENAI_PATCH_ALLOWLIST:
                    found.append(f"{rel}:{line} assigns {_w2_dotted(target)} by hand")
        # monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", ...) / patch.object(ai, "AsyncOpenAI")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.fullmatch(r"[\w.]*\bAsyncOpenAI", node.value)
            and rel not in _ASYNC_OPENAI_PATCH_ALLOWLIST
        ):
            found.append(f"{rel}:{line} patches {node.value!r} by hand")
    return found


def test_no_hand_rolled_openai_fakes() -> None:
    """AC4: outside caption_pipeline_fakes.py no test builds an OpenAI response chain or patches AsyncOpenAI.

    Scans the whole tests tree (the AC names no exception for tests/web). Use the ``fake_openai``
    fixture (or ``FakeOpenAI`` + ``install_fake_openai``) instead.
    """
    offences: list[str] = []
    for rel, source in _w2_test_sources():
        if rel == _SHARED_FAKES_MODULE:
            continue
        offences.extend(_w2_openai_fake_offences(rel, source))
    assert not offences, "hand-rolled OpenAI fakes; use caption_pipeline_fakes.FakeOpenAI:\n" + "\n".join(offences)


@pytest.mark.parametrize(
    "snippet",
    [
        "ai.AsyncOpenAI = FakeClient",
        "publisher_v2.services.ai.AsyncOpenAI = FakeClient",
        'monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", FakeClient)',
    ],
)
def test_openai_fake_scan_flags_every_patch_shape(snippet: str) -> None:
    """AC4 guard self-check: each way of replacing AsyncOpenAI by hand is an offence."""
    assert _w2_openai_fake_offences("test_example.py", snippet)


def test_no_test_subclasses_ai_service() -> None:
    """AC5: no class under tests/ subclasses AIService; build AIService(analyzer, generator) with fakes."""
    import ast

    offenders: list[str] = []
    for rel, source in _w2_test_sources():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef) and any(_w2_dotted(b).split(".")[-1] == "AIService" for b in node.bases):
                offenders.append(f"{rel}:{node.lineno} class {node.name}")
    assert not offenders, "test classes subclass AIService:\n" + "\n".join(offenders)


def _w2_fixture_name(func: object) -> tuple[str, bool] | None:
    """(fixture name, autouse) when ``func`` is decorated with pytest.fixture, else None."""
    import ast

    assert isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef)
    for deco in func.decorator_list:
        call = deco if isinstance(deco, ast.Call) else None
        target = call.func if call else deco
        if _w2_dotted(target).split(".")[-1] != "fixture":
            continue
        name, autouse = func.name, False
        for kw in call.keywords if call else []:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                name = str(kw.value.value)
            if kw.arg == "autouse" and isinstance(kw.value, ast.Constant):
                autouse = bool(kw.value.value)
        return name, autouse
    return None


def test_every_conftest_fixture_is_used() -> None:
    """AC6: every fixture defined in a conftest.py under tests/ has at least one live user.

    A user is a test (or any non-fixture function) requesting it by parameter name, a
    ``usefixtures``/``getfixturevalue`` string, or a fixture that is itself live. Autouse
    fixtures are live by definition. A fixture only requested by dead fixtures is dead too.
    """
    import ast

    conftest_fixtures: dict[str, list[str]] = {}  # name -> ["rel:line", ...]
    autouse: set[str] = set()
    fixture_deps: dict[str, set[str]] = {}  # fixture name -> parameter names it requests
    roots: set[str] = set()
    for rel, source in _w2_test_sources():
        is_conftest = rel.endswith("conftest.py")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and _w2_dotted(node.func).split(".")[-1] in {
                "usefixtures",
                "getfixturevalue",
            }:
                roots.update(a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str))
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            params = {a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
            fixture = _w2_fixture_name(node)
            if fixture is None:
                roots |= params
                continue
            name, is_autouse = fixture
            if is_conftest:
                conftest_fixtures.setdefault(name, []).append(f"{rel}:{node.lineno}")
                fixture_deps.setdefault(name, set()).update(params)
                if is_autouse:
                    autouse.add(name)
            else:
                # Test-module fixtures are counted as users of what they request.
                roots |= params

    live = set(autouse) | (roots & conftest_fixtures.keys())
    frontier = list(live)
    while frontier:
        for dep in fixture_deps.get(frontier.pop(), set()):
            if dep in conftest_fixtures and dep not in live:
                live.add(dep)
                frontier.append(dep)

    unused = sorted(f"{name} ({', '.join(where)})" for name, where in conftest_fixtures.items() if name not in live)
    assert not unused, "conftest fixtures with no live user:\n" + "\n".join(unused)


def test_application_config_built_via_helper() -> None:
    """AC7: tests build ApplicationConfig through make_app_config, not by hand.

    Allowed: the helper's own module and ``_APPLICATION_CONFIG_MODEL_TESTS`` (files that test the
    model itself). Covers the whole suite, tests/web and tests/web_integration included.
    """
    import ast

    offenders: list[str] = []
    for rel, source in _w2_test_sources():
        if rel == _SHARED_FAKES_MODULE or rel in _APPLICATION_CONFIG_MODEL_TESTS:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and _w2_dotted(node.func).split(".")[-1] == "ApplicationConfig":
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, "build ApplicationConfig with caption_pipeline_fakes.make_app_config:\n" + "\n".join(
        offenders
    )


# --- PUB-084 wave 2, #298 (AC8, AC9): web test harness -------------------------------------------

_W2WEB_DIRS = ("web", "web_integration")
_W2WEB_CONFTEST = "web/conftest.py"
# Each external client the web tests fake, keyed by the word a class standing in for it carries
# (case-sensitive: FakeS3, _FakeDropbox, _FakeBot, _ExplodingBot, _FakeSMTP ...).
_W2WEB_FAKE_KINDS = ("S3", "Dropbox", "Bot", "SMTP")
# OpenAI's one fake is caption_pipeline_fakes.FakeOpenAI (AC4); tests/web defines none of its own.
_W2WEB_SHARED_FAKE_KINDS = ("OpenAI",)
# Derived from the real guards (not string literals) so a rename cannot leave the scan stale.
_W2WEB_AUTH_GUARDS = frozenset(fn.__name__ for fn in (web_auth.require_auth, web_auth.require_admin))


def _w2web_sources() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for sub in _W2WEB_DIRS:
        for path in sorted((TESTS_ROOT / sub).rglob("*.py")):
            out.append((str(path.relative_to(TESTS_ROOT)), path.read_text(encoding="utf-8")))
    return out


def _w2web_dotted(node: object) -> str:
    import ast

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_w2web_dotted(node.value)}.{node.attr}"
    return ""


def test_web_fakes_defined_once() -> None:
    """AC8: tests/web holds one S3, Dropbox, Telegram-bot and SMTP fake, all in web/conftest.py.

    The OpenAI fake is the suite-wide ``caption_pipeline_fakes.FakeOpenAI`` (AC4), so tests/web
    defines no OpenAI fake class at all.
    """
    import ast

    definitions: dict[str, list[str]] = {kind: [] for kind in (*_W2WEB_FAKE_KINDS, *_W2WEB_SHARED_FAKE_KINDS)}
    for rel, source in _w2web_sources():
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.ClassDef):
                continue
            for kind in definitions:
                if kind in node.name:
                    definitions[kind].append(f"{rel}:{node.lineno} {node.name}")

    problems = [
        f"{kind}: {sites or 'no definition'}"
        for kind, sites in definitions.items()
        if kind in _W2WEB_FAKE_KINDS and (len(sites) != 1 or not sites[0].startswith(f"{_W2WEB_CONFTEST}:"))
    ]
    problems += [
        f"{kind}: {sites} (use caption_pipeline_fakes.FakeOpenAI)"
        for kind, sites in definitions.items()
        if kind in _W2WEB_SHARED_FAKE_KINDS and sites
    ]
    assert not problems, "each web fake must be defined exactly once, in web/conftest.py:\n" + "\n".join(problems)


def _auth_guard_replacements(rel: str, source: str) -> list[str]:
    """Sites in one file that replace require_auth/require_admin instead of presenting credentials."""
    import ast

    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Call):
            func = _w2web_dotted(node.func)
            if func.split(".")[-1] in ("setattr", "patch", "object", "delattr"):
                for arg in node.args[:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        names.append(arg.value.rsplit(".", 1)[-1])
                    else:
                        names.append(_w2web_dotted(arg).rsplit(".", 1)[-1])
            # app.dependency_overrides.update({require_admin: ...}) / .update(dict(...)) / .setdefault(...)
            elif func.endswith("dependency_overrides.update") or func.endswith("dependency_overrides.setdefault"):
                for sub in (*node.args, *(kw.value for kw in node.keywords)):
                    for inner in ast.walk(sub):
                        if isinstance(inner, ast.Name | ast.Attribute):
                            names.append(_w2web_dotted(inner).rsplit(".", 1)[-1])
                names.extend(kw.arg for kw in node.keywords if kw.arg)
        elif isinstance(node, ast.Subscript) and _w2web_dotted(node.value).endswith("dependency_overrides"):
            names.append(_w2web_dotted(node.slice).rsplit(".", 1)[-1])
        # auth.require_admin = lambda request: None (a plain assignment patch, never undone)
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.extend(t.attr for t in targets if isinstance(t, ast.Attribute))
        if any(name in _W2WEB_AUTH_GUARDS for name in names):
            offenders.append(f"{rel}:{node.lineno}")
    return offenders


@pytest.mark.parametrize(
    "snippet",
    [
        'monkeypatch.setattr("publisher_v2.web.auth.require_admin", lambda r: None)',
        "monkeypatch.setattr(auth, 'require_auth', fake)",
        'patch("publisher_v2.web.app.require_auth")',
        "patch.object(auth, 'require_admin')",
        "app.dependency_overrides[require_auth] = lambda: None",
        "app.dependency_overrides.update({require_admin: lambda: None})",
        "app.dependency_overrides.update({auth.require_auth: noop})",
        "app.dependency_overrides.update(dict([(require_admin, noop)]))",
        "auth.require_admin = lambda request: None",
        "publisher_v2.web.app.require_auth = fake",
    ],
)
def test_auth_patch_scan_flags_every_replacement_shape(snippet: str) -> None:
    """AC9 guard self-check: each way of replacing an auth guard is an offence."""
    assert _auth_guard_replacements("test_example.py", snippet)


def test_auth_patch_scan_ignores_unrelated_overrides() -> None:
    """AC9 guard self-check: overriding other dependencies and assigning other attributes is fine."""
    source = (
        "app.dependency_overrides[get_request_service] = lambda: svc\n"
        "app.dependency_overrides.update({get_request_service: lambda: svc})\n"
        "state.require_something = 1\n"
    )
    assert _auth_guard_replacements("test_example.py", source) == []


def test_no_test_patches_out_auth() -> None:
    """AC9: no test replaces require_auth/require_admin — drive auth through real credentials instead.

    Covers ``monkeypatch.setattr``/``setitem``, ``patch``/``patch.object``, FastAPI
    ``dependency_overrides`` (subscript and ``.update``/``.setdefault``) and plain attribute
    assignment anywhere under publisher_v2/tests.
    """
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if path.resolve() == THIS_FILE:
            continue
        rel = str(path.relative_to(TESTS_ROOT))
        offenders.extend(_auth_guard_replacements(rel, path.read_text(encoding="utf-8")))
    assert not offenders, "tests must not replace require_auth/require_admin:\n" + "\n".join(sorted(set(offenders)))


# --- PUB-084 wave 3, #300 (AC12): no copy-pasted test bodies --------------------------------------

# Test functions whose bodies are identical once constants are stripped, kept apart on purpose.
# Key: "<path relative to tests/>::<Class.>test_name"; value: why it is not parametrised.
# Every member of a duplicate group must be listed, and every entry must still match a live group.
_IDENTICAL_BODY_ALLOWLIST: dict[str, str] = {}


def _normalised_test_bodies() -> dict[str, list[str]]:
    """Map each test body, constants stripped and docstring dropped, to the tests that share it."""
    import ast

    class _StripConstants(ast.NodeTransformer):
        def visit_Constant(self, node: ast.Constant) -> ast.Constant:
            return ast.Constant(value=None)

    def _tests(scope: ast.AST, prefix: str) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
        found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
        for node in ast.iter_child_nodes(scope):
            if isinstance(node, ast.ClassDef):
                found.extend(_tests(node, f"{prefix}{node.name}."))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
                found.append((f"{prefix}{node.name}", node))
        return found

    bodies: dict[str, list[str]] = {}
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        rel = str(path.relative_to(TESTS_ROOT))
        for qualname, func in _tests(ast.parse(path.read_text(encoding="utf-8")), ""):
            body = list(func.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]  # docstring
            if not body:
                continue
            key = "\n".join(ast.dump(_StripConstants().visit(stmt)) for stmt in body)
            bodies.setdefault(key, []).append(f"{rel}::{qualname}")
    return bodies


def test_no_identical_test_bodies() -> None:
    """AC12: no two test functions share a body once constants are stripped, unless allowlisted.

    Two tests that differ only in their literals are one test with a parameter table: use
    ``pytest.mark.parametrize`` with a row per case. A pair kept apart on purpose goes in
    ``_IDENTICAL_BODY_ALLOWLIST`` with the reason.
    """
    groups = [sorted(names) for names in _normalised_test_bodies().values() if len(names) > 1]
    unexplained = [names for names in groups if not all(name in _IDENTICAL_BODY_ALLOWLIST for name in names)]
    grouped = {name for names in groups for name in names}
    stale = sorted(name for name in _IDENTICAL_BODY_ALLOWLIST if name not in grouped)
    missing_reason = sorted(name for name, reason in _IDENTICAL_BODY_ALLOWLIST.items() if not reason.strip())
    problems = [" = ".join(names) for names in sorted(unexplained)]
    problems += [f"stale allowlist entry (no longer duplicated): {name}" for name in stale]
    problems += [f"allowlist entry without a reason: {name}" for name in missing_reason]
    assert not problems, (
        f"{len(unexplained)} group(s) of identical test bodies (constants stripped) — parametrise them:\n"
        + "\n".join(problems)
    )


# --- PUB-084 wave 3, #299 (AC10, AC11): no index.html source greps; e2e out of the default run ----

# A JavaScript function declaration named in a test string: "function foo(", "async function foo\b".
_JS_FUNCTION_DECL = re.compile(r"\bfunction\s+[A-Za-z_$][\w$]*")
# JavaScript statement syntax in a test string: a pinned line of script, not an element contract.
# An id/attribute check ('id="caption-editors"', 'data-filename="a.jpg"') matches none of these.
_JS_STATEMENT = re.compile(
    r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*"  # a declaration: "const maxLen = ..."
    r"|=>|===|!=="  # an arrow function, a strict comparison
    r"|\.addEventListener\("  # a handler registration
    r"|[\w$)\]]\s*;\s*$"  # a statement ending in ";"
    r"|[A-Za-z_$][\w$.]*\([\w$.,\s]*\)"  # a call on plain identifiers: "missingCaptionPlatforms(captions)"
    r"|\{ [A-Za-z_$][\w$, ]* \}"  # object shorthand: "{ captions }"
)
_RE_SEARCHERS = frozenset({"search", "match", "fullmatch", "findall", "finditer", "compile", "sub", "split"})


def _index_function_body_greps(rel: str, source: str) -> list[str]:
    """Sites in one file that grep page script: a regex over, or an ``in`` check for, a JS function or statement."""
    import ast

    offenders: list[str] = []

    def _flag(node: ast.AST) -> None:
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            return
        if _JS_FUNCTION_DECL.search(node.value) or _JS_STATEMENT.search(node.value):
            offenders.append(f"{rel}:{node.lineno} {node.value[:60]!r}")

    for node in ast.walk(ast.parse(source)):
        # re.search(r"async function processUploadQueue\b.*?\n    \}", html, re.DOTALL)
        if isinstance(node, ast.Call) and _w2_dotted(node.func).split(".")[-1] in _RE_SEARCHERS and node.args:
            _flag(node.args[0])
        # assert "function toggleMultiSelect()" in res.text
        elif isinstance(node, ast.Compare) and any(isinstance(op, ast.In | ast.NotIn) for op in node.ops):
            _flag(node.left)
    return offenders


@pytest.mark.parametrize(
    "snippet",
    [
        'match = re.search(r"async function backToGrid\\(\\)\\s*\\{(.*?)\\n    \\}", html, re.DOTALL)',
        'assert "function toggleMultiSelect()" in res.text',
        'assert "async function handleBulkDelete()" not in html',
        'pattern = re.compile(r"function setUploadLockState\\b.*?\\n    \\}")',
        # JavaScript statements, not just function declarations (#305 review nit).
        'assert "const maxLen = platformLimits[platform];" in html',
        'assert "let pending = 0" in html',
        'assert "var legacy" not in html',
        'assert "items.map((item) => item.name)" in html',
        'assert "text === legacyCaption" in html',
        "assert 'featureConfig.auth_mode !== \"auth0\"' in html",
        "assert \"btn.addEventListener('click'\" in html",
        'assert \'xhr.open("POST", "/api/library/upload");\' in html',
        'assert "missingCaptionPlatforms(captions)" in html',
        'assert "{ captions }" in html',
        'assert re.search(r"const fromLegacy = .*;", html)',
    ],
)
def test_index_function_body_scan_flags_every_grep_shape(snippet: str) -> None:
    """AC10 guard self-check: a regex over, or a substring check for, a JS function or statement is an offence."""
    assert _index_function_body_greps("test_example.py", snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        "assert 'id=\"caption-editors\"' in html",
        "assert 'id=\"caption-text\"' not in html",
        "assert 'data-filename=\"alpha.jpg\"' in html",
        "assert 'type=\"password\"' not in html",
        'assert "/api/admin/login" not in html',
        'assert "cover every enabled platform" in res.text',
        'assert "Publisher V2 Web" in res.text',
    ],
)
def test_index_function_body_scan_allows_element_contract_checks(snippet: str) -> None:
    """AC10 guard self-check: element ids, attributes and visible text stay checkable in served HTML."""
    assert not _index_function_body_greps("test_example.py", snippet)


def test_no_test_greps_index_html_function_bodies() -> None:
    """AC10: no test regex-matches or substring-checks a JavaScript function in index.html's source.

    Pin the page's element contract in ``web/test_index_contract.py`` (ids, attributes, zones) and
    its behaviour in the browser flows under ``tests/e2e``; the script itself stays free to change.
    """
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if path.resolve() == THIS_FILE or "__pycache__" in path.parts:
            continue
        offenders.extend(_index_function_body_greps(path.relative_to(TESTS_ROOT).as_posix(), path.read_text("utf-8")))
    assert not offenders, (
        "tests grep index.html JavaScript (functions or statements) — pin ids/attributes in "
        "web/test_index_contract.py and behaviour in tests/e2e instead:\n" + "\n".join(offenders)
    )


def test_default_run_deselects_e2e(pytestconfig: pytest.Config) -> None:
    """AC11: the ``e2e`` marker is registered and pyproject addopts deselects it from the default run.

    ``uv run pytest`` (and the commit hook, which runs it) therefore needs no browser; a ``-m`` on
    the command line, e.g. ``uv run pytest -m e2e``, overrides the default expression. Every module
    under ``tests/e2e`` carries the marker module-wide, so none of it leaks into the default run.
    """
    import ast
    import tomllib

    ini = tomllib.loads((pytestconfig.rootpath / "pyproject.toml").read_text("utf-8"))["tool"]["pytest"]["ini_options"]
    markers = [line.split(":", 1)[0].strip() for line in ini.get("markers", [])]
    assert "e2e" in markers, f"register the e2e marker in [tool.pytest.ini_options] markers: {markers}"

    addopts = ini.get("addopts", [])
    addopts = addopts.split() if isinstance(addopts, str) else list(addopts)
    expressions = [addopts[i + 1] for i, opt in enumerate(addopts[:-1]) if opt == "-m"]
    expressions += [opt.split("=", 1)[1] for opt in addopts if opt.startswith("-m=")]
    assert expressions, f"addopts must pass a default -m expression deselecting e2e: {addopts}"
    assert re.fullmatch(r"\s*not\s+e2e\s*", expressions[-1]), f"default -m must be 'not e2e', got {expressions[-1]!r}"

    e2e_dir = TESTS_ROOT / "e2e"
    assert e2e_dir.is_dir(), "the e2e suite lives in tests/e2e"
    unmarked: list[str] = []
    for path in sorted(e2e_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        marked = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
            and "e2e" in ast.unparse(node.value)
            for node in tree.body
        )
        if not marked:
            unmarked.append(path.name)
    assert not unmarked, "tests/e2e modules without `pytestmark = pytest.mark.e2e`: " + ", ".join(unmarked)
