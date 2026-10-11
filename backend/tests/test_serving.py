from fastapi.testclient import TestClient
from scripts.serve_app import app


def test_static_host_api_slashes_do_not_redirect():
    with TestClient(app, follow_redirects=False) as client:
        for path in ("/api/health", "/api/health/", "/api/projects", "/api/projects/"):
            response = client.get(path)
            assert response.status_code == 200
            assert "location" not in response.headers


def test_post_body_survives_api_slash_normalization(monkeypatch):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    with TestClient(app, follow_redirects=False) as client:
        response = client.post("/api/sessions/", json={"role": "buyer"})
        assert response.status_code == 200
        assert response.json()["role"] == "buyer"
