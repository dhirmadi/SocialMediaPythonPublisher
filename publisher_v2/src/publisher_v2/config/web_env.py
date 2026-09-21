"""Build web and Auth0 config straight from environment variables.

Used by the orchestrator-backed runtime path, where the web layer is needed
before (or without) a full application config.
"""

import os

from publisher_v2.config.schema import Auth0Config, WebConfig
from publisher_v2.core.exceptions import ConfigurationError


def load_web_and_auth0_from_env() -> tuple[WebConfig, Auth0Config | None]:
    """Build ``(WebConfig, Auth0Config | None)`` from the process environment.

    Load web/auth0 config from environment variables without requiring full
    application config (used by orchestrator-backed runtime config). The
    WebConfig is always returned (its own env-backed defaults apply). Auth0 is
    only built when both AUTH0_DOMAIN and AUTH0_CLIENT_ID are set — otherwise
    None, which means no admin login is available.

    Raises:
        ConfigurationError: Auth0 is half-configured, i.e. domain and client id
            are present but a required variable such as AUTH0_CLIENT_SECRET is
            missing.
    """
    web_cfg = WebConfig()

    auth0_cfg: Auth0Config | None = None
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
