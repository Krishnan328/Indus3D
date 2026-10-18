import os
import pytest
from api.server import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_frontend_fallback_when_dist_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # In testing environment where frontend/dist isn't built, returns status json
    data = resp.get_json()
    assert "Indus3D backend running" in data.get("status", "")

def test_api_routes_not_swallowed_by_frontend(client):
    resp = client.get("/api/v1/nonexistent_route_test")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data.get("error") == "Not found"

def test_ws_path_guard(client):
    resp = client.get("/ws")
    assert resp.status_code == 404
