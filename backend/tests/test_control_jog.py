import pytest
from api.server import app

@pytest.fixture
def test_client():
    app.config["TESTING"] = True
    return app.test_client()

def test_jog_with_null_feedrate_succeeds(test_client, monkeypatch):
    monkeypatch.setattr("api.server._run_managed_gcode", lambda gcode: {"status": "ok", "gcode": gcode})
    monkeypatch.setattr("api.server._worker", lambda: None)

    # Simulates JSON.stringify({ x: 10, feedrate: NaN }) -> {"x": 10, "feedrate": null}
    resp = test_client.post("/api/v1/control/jog", json={"x": 10, "feedrate": None})
    assert resp.status_code == 200
    assert "X10.000" in resp.json["gcode"]
    assert "F3000" in resp.json["gcode"]

def test_jog_with_explicit_feedrate(test_client, monkeypatch):
    monkeypatch.setattr("api.server._run_managed_gcode", lambda gcode: {"status": "ok", "gcode": gcode})
    monkeypatch.setattr("api.server._worker", lambda: None)

    resp = test_client.post("/api/v1/control/jog", json={"z": 5, "feedrate": 600})
    assert resp.status_code == 200
    assert "Z5.000" in resp.json["gcode"]
    assert "F600" in resp.json["gcode"]

def test_jog_with_empty_axes_rejected(test_client, monkeypatch):
    monkeypatch.setattr("api.server._worker", lambda: None)
    resp = test_client.post("/api/v1/control/jog", json={"feedrate": 3000})
    assert resp.status_code == 400
    assert "non-zero" in resp.json["error"]

def test_jog_with_invalid_feedrate_rejected(test_client, monkeypatch):
    monkeypatch.setattr("api.server._worker", lambda: None)
    resp = test_client.post("/api/v1/control/jog", json={"x": 10, "feedrate": 50000})
    assert resp.status_code == 400
    assert "Feedrate must be between" in resp.json["error"]
