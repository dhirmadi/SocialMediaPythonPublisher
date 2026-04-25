"""Tests for PUB-029 AC-06: admin-only /api/config/voice-profile endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from publisher_v2.web.auth import ADMIN_COOKIE_NAME


def _admin(client: TestClient) -> TestClient:
    client.cookies.set(ADMIN_COOKIE_NAME, "1")
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
