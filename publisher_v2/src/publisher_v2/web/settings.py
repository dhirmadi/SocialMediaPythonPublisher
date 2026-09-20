"""Accessor for the process-wide :class:`RuntimeSettings` instance (#143).

The web process parses the environment once in the FastAPI lifespan and stores
the result on ``app.state.runtime_settings``. Request-path code reads it from
there via :func:`get_runtime_settings` instead of re-parsing the environment on
every request.

The fallback exists for the two cases where no app state is available: code
constructed outside a request (CLI, unit tests) and requests served by an app
whose lifespan has not run. It keeps the historical "fresh env read" behaviour
so per-process overrides still apply.
"""

from __future__ import annotations

import logging

from fastapi import Request

from publisher_v2.config.runtime_settings import RuntimeSettings, load_runtime_settings
from publisher_v2.utils.logging import log_json

logger = logging.getLogger("publisher_v2.web.settings")


def get_runtime_settings(request: Request | None) -> RuntimeSettings:
    """Settings for this request: the instance built at startup, else a fresh parse.

    The fresh-parse fallback is a CLI/test path only — it is not a supported
    production path. In the web process the lifespan always populates
    ``app.state.runtime_settings``, and hitting the fallback there would mean
    re-parsing the environment on a request.

    ``request`` is required rather than defaulted to ``None``: a caller with no
    request must say so, since ``get_runtime_settings()`` would otherwise be a
    service locator that re-parses the environment — the thing #143 removed —
    and would read as an ordinary snapshot lookup at the call site.
    """
    if request is not None:
        # Starlette raises KeyError for ``request.app`` when the ASGI scope has
        # no app (hand-built Request objects in tests) — treat that as "no state".
        try:
            candidate = getattr(request.app.state, "runtime_settings", None)
        except (AttributeError, KeyError):
            candidate = None
        if isinstance(candidate, RuntimeSettings):
            return candidate
    # A fallback parse in a served request means the lifespan never ran — log it,
    # so a deployment that loses the snapshot is observable instead of silent.
    if request is not None:
        log_json(logger, logging.DEBUG, "runtime_settings_fallback_parse")
    return load_runtime_settings()
