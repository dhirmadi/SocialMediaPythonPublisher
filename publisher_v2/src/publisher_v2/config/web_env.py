from __future__ import annotations

import os
from typing import Optional

from publisher_v2.config.schema import Auth0Config, WebConfig
from publisher_v2.core.exceptions import ConfigurationError


def load_web_and_auth0_from_env() -> tuple[WebConfig, Optional[Auth0Config]]:
    """
    Load web/auth0 config from environment variables without requiring full
    application config (used by orchestrator-backed runtime config).
    """
    web_cfg = WebConfig()

    auth0_cfg: Optional[Auth0Config] = None
    if os.environ.get("AUTH0_DOMAIN") and os.environ.get("AUTH0_CLIENT_ID"):
        try:
            auth0_cfg = Auth0Config(
                domain=os.environ["AUTH0_DOMAIN"],
                client_id=os.environ["AUTH0_CLIENT_ID"],
                client_secret=os.environ["AUTH0_CLIENT_SECRET"],
                audience=os.environ.get("AUTH0_AUDIENCE"),
                callback_url=os.environ.get("AUTH0_CALLBACK_URL"),
                admin_emails=os.environ.get("ADMIN_LOGIN_EMAILS")
                or os.environ.get("AUTH0_ADMIN_EMAIL_ALLOWLIST")
                or "",
            )
        except KeyError as exc:
            raise ConfigurationError(f"Missing required Auth0 environment variable: {exc}") from exc

    return web_cfg, auth0_cfg


