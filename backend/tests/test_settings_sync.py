import pytest
import json
from unittest.mock import MagicMock
from api.server import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()

def test_settings_sync_get_fallback_local(client, monkeypatch):
    from api.system_host import Unreachable
    monkeypatch.setattr("api.system_host.call", MagicMock(side_effect=Unreachable("Moonraker unreachable")))
    resp = client.get("/api/v1/settings/sync")
    assert resp.status_code == 200
    data = resp.json
    assert data["ok"] is True
    assert "settings" in data

def test_settings_sync_post_and_get(client, monkeypatch):
    recorded_calls = []
    def mock_call(method, route, body=None, timeout=None):
        recorded_calls.append((method, route, body))
        if method == "GET":
            return {"value": {"theme": "soft-dark", "language": "de"}}
        return {"result": "ok"}

    monkeypatch.setattr("api.system_host.call", mock_call)

    # 1. Post settings
    payload = {"theme": "soft-dark", "language": "de"}
    post_resp = client.post("/api/v1/settings/sync", json=payload)
    assert post_resp.status_code == 200
    assert post_resp.json["ok"] is True
    assert post_resp.json["settings"]["theme"] == "soft-dark"

    # 2. Get settings
    get_resp = client.get("/api/v1/settings/sync")
    assert get_resp.status_code == 200
    assert get_resp.json["ok"] is True
    assert get_resp.json["settings"]["theme"] == "soft-dark"
    assert get_resp.json["settings"]["language"] == "de"
