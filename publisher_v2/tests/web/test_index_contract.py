"""The admin page's element contract (PUB-084 #299, AC10).

One fetch of ``GET /`` per module, parsed into a DOM index, checked against a table of the element
ids the page's script and the e2e flows (``tests/e2e``) drive: which element carries the id, the
attributes and load-time classes it needs, and the zone it sits in. Nothing here reads the page's
JavaScript: behaviour (upload lock, bulk-delete retry, one request per action, logout) is pinned by
the browser flows, so the script can be refactored freely (#277) while this table stays green.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from .conftest import MANAGED_ENV

_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"})


@dataclass(frozen=True)
class Hook:
    """One required element.

    ``attrs``: attribute -> exact value (``None``: the attribute is present). ``classes``: class
    tokens it carries as served (before any script runs). ``within``: a class token some ancestor
    carries. ``options``/``selected``: a ``<select>``'s option values and its preselected value.
    ``text``: a substring of its visible text.
    """

    id: str
    tag: str
    attrs: Mapping[str, str | None] = field(default_factory=dict)
    classes: tuple[str, ...] = ()
    within: str | None = None
    options: tuple[str, ...] = ()
    selected: str | None = None
    text: str | None = None


@dataclass
class _Element:
    tag: str
    attrs: dict[str, str | None]
    ancestor_classes: frozenset[str]
    options: list[str] = field(default_factory=list)
    selected: str | None = None
    text: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())


class _DomIndex(HTMLParser):
    """Index every element that has an ``id``, with its ancestors' classes, options and text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.by_id: dict[str, list[_Element]] = {}
        self._open: list[tuple[str, set[str], _Element | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        ancestors = frozenset(cls for _, classes, _ in self._open for cls in classes)
        element = _Element(tag, values, ancestors) if values.get("id") else None
        if element is not None:
            self.by_id.setdefault(str(values["id"]), []).append(element)
        if tag == "option":
            for _, _, owner in reversed(self._open):
                if owner is not None and owner.tag == "select":
                    owner.options.append(values.get("value") or "")
                    if "selected" in values:
                        owner.selected = values.get("value")
                    break
        if tag not in _VOID_TAGS:
            self._open.append((tag, set((values.get("class") or "").split()), element))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index][0] == tag:
                del self._open[index:]
                return

    def handle_data(self, data: str) -> None:
        for _, _, element in self._open:
            if element is not None:
                element.text.append(data)


REQUIRED_HOOKS: tuple[Hook, ...] = (
    # Header: Auth0 login link and the logout control (#91 SEC-8 POST logout, #272).
    Hook("btn-admin", "a"),
    Hook("btn-admin-logout", "button", attrs={"type": "button"}, classes=("admin-only", "hidden")),
    # Detail view: the image, navigation, and the admin actions (PUB-033).
    Hook("image", "img", within="image-container"),
    Hook("image-placeholder", "div", within="image-container"),
    Hook("btn-prev", "button", classes=("hidden",), within="image-container"),
    Hook("btn-next", "button", within="image-container"),
    Hook("btn-back-to-grid", "button", classes=("admin-only", "hidden")),
    Hook("btn-login-cta", "button", classes=("hidden",)),
    Hook("admin-controls", "div", classes=("admin-only", "hidden")),
    Hook("btn-analyze", "button", within="admin-only"),
    Hook("btn-publish", "button", within="admin-only"),
    Hook("btn-keep", "button", within="admin-only"),
    Hook("btn-remove", "button", within="admin-only"),
    Hook("btn-delete", "button", within="admin-only"),
    Hook("panel-caption", "div", classes=("panel", "admin-only", "hidden")),
    Hook("panel-activity", "div", classes=("panel", "admin-only", "hidden"), text="Activity"),
    Hook("status", "div", within="panel"),
    # Unified grid panel (PUB-033), find zone (PUB-038) with the page-size selector (PUB-044).
    Hook("panel-grid", "div", classes=("panel", "hidden")),
    Hook("grid-search", "input", attrs={"type": "text"}, within="toolbar-find"),
    Hook("grid-sort", "select", within="toolbar-find", options=("name", "last_modified", "size")),
    Hook("grid-order-toggle", "button", classes=("toolbar-order-btn",), within="toolbar-find"),
    Hook("grid-page-size", "select", within="toolbar-find", options=("10", "25", "50", "100"), selected="25"),
    # Actions zone (PUB-038): upload (PUB-036) and refresh.
    Hook("grid-upload-label", "label", classes=("toolbar-upload", "hidden"), within="toolbar-actions"),
    Hook(
        "grid-upload-input",
        "input",
        attrs={"type": "file", "accept": "image/jpeg,image/png", "multiple": None},
        within="toolbar-actions",
    ),
    Hook("grid-refresh-btn", "button", within="toolbar-actions"),
    # Result count and the multi-select toggle below the zones (PUB-038, PUB-037).
    Hook("grid-result-count", "div", within="toolbar-meta"),
    Hook("grid-select-toggle", "button", classes=("toolbar-select-toggle", "hidden"), within="toolbar-meta"),
    # Multi-select bar (PUB-037).
    Hook("grid-select-bar", "div", classes=("grid-select-bar", "hidden")),
    Hook("grid-select-all", "button", within="grid-select-bar"),
    Hook("grid-select-count", "span", within="grid-select-bar"),
    Hook("grid-delete-selected", "button", classes=("danger", "hidden"), within="grid-select-bar"),
    # Upload queue (PUB-036) and its lock banner (PUB-042).
    Hook("upload-queue", "div", attrs={"aria-live": "polite"}, classes=("queue-panel", "hidden")),
    Hook("upload-queue-title", "span", within="queue-panel"),
    Hook("upload-queue-summary", "span", attrs={"role": "status"}, within="queue-panel"),
    Hook("upload-queue-dismiss", "button", classes=("queue-dismiss",), within="queue-panel"),
    Hook(
        "upload-queue-status",
        "div",
        attrs={"role": "status"},
        classes=("hidden",),
        within="queue-panel",
        text="please wait",
    ),
    Hook("upload-queue-list", "div", within="queue-panel"),
    # Delete queue (PUB-037).
    Hook("delete-queue", "div", attrs={"aria-live": "polite"}, classes=("queue-panel", "hidden")),
    Hook("delete-queue-title", "span", within="queue-panel"),
    Hook("delete-queue-summary", "span", attrs={"role": "status"}, within="queue-panel"),
    Hook("delete-queue-dismiss", "button", classes=("queue-dismiss",), within="queue-panel"),
    Hook("delete-queue-list", "div", within="queue-panel"),
    # Grid body and pagination (PUB-033).
    Hook("grid-container", "div", classes=("browse-grid",)),
    Hook("grid-empty", "div", classes=("hidden",)),
    Hook("grid-pagination", "div", classes=("hidden",)),
    Hook("grid-prev", "button", within="browse-pagination"),
    Hook("grid-pages", "span", within="browse-pagination"),
    Hook("grid-next", "button", within="browse-pagination"),
)


@pytest.fixture(scope="module")
def index_dom() -> Iterator[dict[str, list[_Element]]]:
    """``GET /`` on the real app, fetched once for the module and indexed by element id."""
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import app
    from publisher_v2.web.dependencies import get_service

    with pytest.MonkeyPatch.context() as mp:
        for key, value in MANAGED_ENV.items():
            mp.setenv(key, value)
        for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH"):
            mp.delenv(key, raising=False)
        get_config_source.cache_clear()
        get_service.cache_clear()
        try:
            response = TestClient(app).get("/")
        finally:
            get_config_source.cache_clear()
            get_service.cache_clear()
    assert response.status_code == 200, response.text[:500]
    parser = _DomIndex()
    parser.feed(response.text)
    parser.close()
    yield parser.by_id


@pytest.mark.parametrize("hook", REQUIRED_HOOKS, ids=[hook.id for hook in REQUIRED_HOOKS])
def test_index_exposes_required_hook(index_dom: dict[str, list[_Element]], hook: Hook) -> None:
    """AC10: the served page has exactly one ``#<id>`` element shaped as the UI contract requires."""
    found = index_dom.get(hook.id, [])
    assert len(found) == 1, f"expected exactly one #{hook.id}, found {len(found)}"
    element = found[0]
    assert element.tag == hook.tag, f"#{hook.id} is a <{element.tag}>, expected <{hook.tag}>"
    for name, value in hook.attrs.items():
        assert name in element.attrs, f"#{hook.id} lacks the {name} attribute"
        if value is not None:
            assert element.attrs[name] == value, f"#{hook.id} {name}={element.attrs[name]!r}, expected {value!r}"
    missing = set(hook.classes) - element.classes
    assert not missing, f"#{hook.id} is served without class(es) {sorted(missing)}"
    if hook.within is not None:
        assert hook.within in element.ancestor_classes, f"#{hook.id} is not inside a .{hook.within} element"
    if hook.options:
        assert tuple(element.options) == hook.options, f"#{hook.id} offers {element.options}"
    if hook.selected is not None:
        assert element.selected == hook.selected, f"#{hook.id} preselects {element.selected!r}"
    if hook.text is not None:
        assert hook.text in " ".join("".join(element.text).split()), f"#{hook.id} text lacks {hook.text!r}"
