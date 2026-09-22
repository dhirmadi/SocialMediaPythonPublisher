"""Tests for PUB-029 AC-06: admin-only /api/config/voice-profile endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from publisher_v2.config.schema import FeaturesConfig
from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value


def _features() -> FeaturesConfig:
    """The real config the app serves requests from (env-first singleton)."""
    from publisher_v2.web.dependencies import get_service

    return get_service().config.features


def _admin(client: TestClient) -> TestClient:
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host="testserver"))
    # Browser callers send X-Requested-With via the installed fetch wrapper;
    # CSRF middleware requires it for state-changing requests.
    client.headers.update({"X-Requested-With": "XMLHttpRequest"})
    return client


# ---------------------------------------------------------------------------
# AC-06: GET returns the current voice profile (admin only)
# ---------------------------------------------------------------------------


class TestVoiceProfileGet:
    def test_get_requires_admin(self, managed_admin_client: TestClient) -> None:
        # No admin cookie set
        managed_admin_client.cookies.clear()
        res = managed_admin_client.get("/api/config/voice-profile")
        assert res.status_code in (401, 403)

    def test_get_returns_current_profile_for_admin(self, managed_admin_client: TestClient) -> None:
        client = _admin(managed_admin_client)
        res = client.get("/api/config/voice-profile")
        assert res.status_code == 200
        body = res.json()
        # Schema: { "voice_profile": list[str] | None, "enabled": bool }
        assert "voice_profile" in body
        assert "enabled" in body


# ---------------------------------------------------------------------------
# AC-06: POST updates the runtime voice profile (admin only)
# ---------------------------------------------------------------------------


class TestVoiceProfilePost:
    def test_post_requires_admin(self, managed_admin_client: TestClient) -> None:
        managed_admin_client.cookies.clear()
        res = managed_admin_client.post(
            "/api/config/voice-profile",
            json={"voice_profile": ["one", "two"]},
        )
        assert res.status_code in (401, 403)

    def test_post_updates_profile_in_memory(self, managed_admin_client: TestClient) -> None:
        client = _admin(managed_admin_client)
        res = client.post(
            "/api/config/voice-profile",
            json={"voice_profile": ["My voice line.", "Another line."]},
        )
        assert res.status_code == 200
        # GET reflects the update
        get_res = client.get("/api/config/voice-profile")
        assert get_res.status_code == 200
        body = get_res.json()
        assert body["voice_profile"] == ["My voice line.", "Another line."]

    def test_adding_a_profile_at_runtime_turns_matching_on(self, managed_admin_client: TestClient) -> None:
        """#131 review: the POST assigned the profile without re-deriving the default.

        The whole point of #131 is that a tenant with a profile and no explicit
        flag gets matching on. A profile added through this endpoint left it off
        until the process restarted — the response even said `enabled: false`
        while holding the profile that should have enabled it.
        """
        client = _admin(managed_admin_client)

        res = client.post(
            "/api/config/voice-profile",
            json={"voice_profile": ["My voice line.", "Another line."]},
        )

        assert res.status_code == 200
        assert res.json()["enabled"] is True, "a profile was stored but matching stayed off"

    def test_clearing_a_profile_at_runtime_turns_matching_off(self, managed_admin_client: TestClient) -> None:
        """The derived default is symmetric: no profile means nothing to match."""
        client = _admin(managed_admin_client)
        client.post("/api/config/voice-profile", json={"voice_profile": ["a", "b"]})

        res = client.post("/api/config/voice-profile", json={"voice_profile": []})

        assert res.status_code == 200
        assert res.json()["enabled"] is False

    def test_clearing_a_profile_turns_matching_off_for_a_tenant_that_booted_with_one(
        self, monkeypatch, env_first_config: None
    ) -> None:
        """#131 review: the other clearing test never reaches production's state.

        The population this issue is about BOOTS with a profile, so the default
        is derived during config load rather than by the endpoint. If that
        derivation marks the flag as explicitly set, clearing the profile here
        leaves `enabled: true` beside a null profile — the mirror image of the
        defect the endpoint fix was for.
        """
        import json

        from fastapi.testclient import TestClient

        from publisher_v2.config.source import get_config_source
        from publisher_v2.web.app import app
        from publisher_v2.web.dependencies import get_service

        # Same admin setup as `managed_admin_client`, but booting WITH a profile.
        monkeypatch.setenv("CONTENT_SETTINGS", json.dumps({"voice_profile": ["A line.", "Another."]}))
        monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
        # #137: Auth0 is the only admin login; web_admin_pw no longer exists.
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
        monkeypatch.setenv("AUTH0_CLIENT_SECRET", "cs")
        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
        monkeypatch.setenv("WEB_DEBUG", "true")
        monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
        monkeypatch.setenv("CONFIG_SOURCE", "env")
        monkeypatch.delenv("FEATURE_VOICE_MATCHING", raising=False)
        get_config_source.cache_clear()
        get_service.cache_clear()

        client = _admin(TestClient(app))
        assert client.get("/api/config/voice-profile").json()["enabled"] is True, "boot-time derivation failed"

        res = client.post("/api/config/voice-profile", json={"voice_profile": []})

        assert res.status_code == 200
        assert res.json()["voice_profile"] is None
        assert res.json()["enabled"] is False, "a derived flag survived the profile it was derived from"

    def test_an_explicit_flag_still_wins_over_the_runtime_default(self, managed_admin_client: TestClient) -> None:
        """Precedence is unchanged: an operator who set the flag keeps their choice."""
        client = _admin(managed_admin_client)
        features = _features()
        was_set = "voice_matching_enabled" in features.model_fields_set
        previous = features.voice_matching_enabled
        features.voice_matching_enabled = False
        features.model_fields_set.add("voice_matching_enabled")
        try:
            res = client.post("/api/config/voice-profile", json={"voice_profile": ["a"]})

            assert res.status_code == 200
            assert res.json()["enabled"] is False, "an explicit false was overridden by the derived default"
        finally:
            # Restore what this test deliberately forced onto the shared
            # config. `env_first_config` already clears the service cache per
            # test, so this is belt-and-braces rather than load-bearing.
            features.voice_matching_enabled = previous
            if not was_set:
                features.model_fields_set.discard("voice_matching_enabled")

    def test_post_clears_profile_with_empty_list(self, managed_admin_client: TestClient) -> None:
        client = _admin(managed_admin_client)
        client.post("/api/config/voice-profile", json={"voice_profile": ["a", "b"]})
        res = client.post("/api/config/voice-profile", json={"voice_profile": []})
        assert res.status_code == 200
        get_res = client.get("/api/config/voice-profile")
        body = get_res.json()
        assert body["voice_profile"] in (None, [])

    def test_post_rejects_too_many_examples(self, managed_admin_client: TestClient) -> None:
        client = _admin(managed_admin_client)
        # Schema validator caps at 20.
        res = client.post(
            "/api/config/voice-profile",
            json={"voice_profile": [f"e{i}" for i in range(21)]},
        )
        assert res.status_code in (400, 422)


# ---------------------------------------------------------------------------
# PUB-048 AC1 (#187): strict mode is enforced by require_admin itself, so the
# voice-profile routes (require_admin-only today) cannot forget it.
# ---------------------------------------------------------------------------


class TestVoiceProfileStrictMode:
    """AC1: `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE=1` + cookie only -> 401 on both verbs."""

    _STRICT_DETAIL = "Header authentication required in addition to the admin cookie"

    @staticmethod
    def _strict(monkeypatch: pytest.MonkeyPatch) -> None:
        """Strict mode is only meaningful when a header backend is configured."""
        monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
        monkeypatch.setenv("WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE", "1")

    def test_get_requires_admin_under_strict_mode_with_cookie_only(
        self, managed_admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._strict(monkeypatch)
        client = _admin(managed_admin_client)

        res = client.get("/api/config/voice-profile")

        assert res.status_code == 401, "a cookie alone defeated strict mode on GET /api/config/voice-profile"
        assert res.json()["detail"] == self._STRICT_DETAIL

    def test_post_requires_admin_under_strict_mode_with_cookie_only(
        self, managed_admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._strict(monkeypatch)
        client = _admin(managed_admin_client)

        res = client.post("/api/config/voice-profile", json={"voice_profile": ["injected line."]})

        assert res.status_code == 401, "a cookie alone defeated strict mode on POST /api/config/voice-profile"
        assert res.json()["detail"] == self._STRICT_DETAIL
        # The profile feeds the caption prompt: a rejected request must not have written it.
        allowed = _admin(managed_admin_client)
        monkeypatch.delenv("WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE", raising=False)
        assert "injected line." not in (allowed.get("/api/config/voice-profile").json()["voice_profile"] or [])
