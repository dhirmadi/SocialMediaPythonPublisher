import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from publisher_v2.web.app import app

@pytest.fixture
def client():
    # Set required env vars for session middleware and admin password
    env_vars = {
        "WEB_SESSION_SECRET": "test-secret",
        "WEB_DEBUG": "1",
        "web_admin_pw": "secret123"
    }
    with patch.dict("os.environ", env_vars):
        from publisher_v2.web.app import app
        with TestClient(app) as c:
            yield c

def test_legacy_login_success(client):
    response = client.post("/api/admin/login", json={"password": "secret123"})
    assert response.status_code == 200
    assert response.json()["admin"] is True
    assert "pv2_admin" in response.cookies

def test_legacy_login_invalid_password(client):
    response = client.post("/api/admin/login", json={"password": "wrong"})
    assert response.status_code == 401
    assert "pv2_admin" not in response.cookies

def test_legacy_login_disabled_when_no_password():
    # Patch environ to remove web_admin_pw
    with patch.dict("os.environ", {"web_admin_pw": ""}):
        # Re-create client to pick up env change if needed, or just rely on the patch 
        # since get_admin_password reads os.environ directly.
        # However, TestClient context might be tricky if app startup logic cached things, 
        # but get_admin_password() is called at request time.
        
        # We need to ensure we have a valid session secret still
        with patch.dict("os.environ", {"WEB_SESSION_SECRET": "test", "WEB_DEBUG": "1"}):
             with TestClient(app) as c:
                response = c.post("/api/admin/login", json={"password": "any"})
                assert response.status_code == 404
                assert "Legacy login not enabled" in response.json()["detail"]

