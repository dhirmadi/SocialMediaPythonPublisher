import pytest

from publisher_v2.config.orchestrator_models import OrchestratorAuth, OrchestratorConfigV2, OrchestratorFeatures, OrchestratorStorage, OrchestratorStoragePaths
from publisher_v2.config.schema import Auth0Config
from publisher_v2.config.source import _apply_orchestrator_auth_policy


def _base_cfg_v2(*, auth: OrchestratorAuth | None) -> OrchestratorConfigV2:
    return OrchestratorConfigV2(
        features=OrchestratorFeatures(),
        storage=OrchestratorStorage(
            provider="dropbox",
            credentials_ref="ref",
            paths=OrchestratorStoragePaths(root="/root"),
        ),
        auth=auth,
    )


def test_orchestrator_auth_disabled_disables_auth0_even_if_env_present() -> None:
    auth0 = Auth0Config(
        domain="d",
        client_id="i",
        client_secret="s",
        callback_url=None,
        admin_emails="env@example.com",
        audience=None,
    )
    cfg = _base_cfg_v2(auth=OrchestratorAuth(enabled=False, allowed_emails=["a@example.com"]))
    assert _apply_orchestrator_auth_policy(auth0, cfg) is None


def test_orchestrator_auth_enabled_overrides_admin_allowlist() -> None:
    auth0 = Auth0Config(
        domain="d",
        client_id="i",
        client_secret="s",
        callback_url=None,
        admin_emails="env@example.com",
        audience=None,
    )
    cfg = _base_cfg_v2(auth=OrchestratorAuth(enabled=True, allowed_emails=["a@example.com", " B@EXAMPLE.COM "]))
    out = _apply_orchestrator_auth_policy(auth0, cfg)
    assert out is not None
    assert out.admin_emails_list == ["a@example.com", "B@EXAMPLE.COM"]


def test_orchestrator_auth_enabled_requires_env_auth0() -> None:
    cfg = _base_cfg_v2(auth=OrchestratorAuth(enabled=True, allowed_emails=["a@example.com"]))
    with pytest.raises(Exception):
        _apply_orchestrator_auth_policy(None, cfg)


