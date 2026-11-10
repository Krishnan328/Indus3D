import pytest
from api.server import app

@pytest.fixture
def test_client():
    app.config["TESTING"] = True
    return app.test_client()

def test_move_with_null_feedrate_succeeds(test_client, monkeypatch):
    monkeypatch.setattr("api.server._run_managed_gcode", lambda gcode: {"status": "ok", "gcode": gcode})
    monkeypatch.setattr("api.server._worker", lambda: None)

    resp = test_client.post("/api/v1/control/move", json={"x": 100, "y": 50, "feedrate": None})
    assert resp.status_code == 200
    assert "G90" in resp.json["gcode"]
    assert "X100.000" in resp.json["gcode"]
    assert "Y50.000" in resp.json["gcode"]
    assert "F3000" in resp.json["gcode"]

def test_move_with_explicit_feedrate(test_client, monkeypatch):
    monkeypatch.setattr("api.server._run_managed_gcode", lambda gcode: {"status": "ok", "gcode": gcode})
    monkeypatch.setattr("api.server._worker", lambda: None)

    resp = test_client.post("/api/v1/control/move", json={"z": 15.5, "feedrate": 600})
    assert resp.status_code == 200
    assert "G90" in resp.json["gcode"]
    assert "Z15.500" in resp.json["gcode"]
    assert "F600" in resp.json["gcode"]

def test_move_with_empty_axes_rejected(test_client, monkeypatch):
    monkeypatch.setattr("api.server._worker", lambda: None)
    resp = test_client.post("/api/v1/control/move", json={"feedrate": 3000})
    assert resp.status_code == 400
    assert "At least one axis" in resp.json["error"]

def test_move_with_invalid_feedrate_rejected(test_client, monkeypatch):
    monkeypatch.setattr("api.server._worker", lambda: None)
    resp = test_client.post("/api/v1/control/move", json={"x": 50, "feedrate": 50000})
    assert resp.status_code == 400
    assert "Feedrate must be between" in resp.json["error"]

def test_move_when_printing_blocked(test_client, monkeypatch):
    class BusyWorker:
        latest = {"print_state": "printing"}
    monkeypatch.setattr("api.server._worker", lambda: BusyWorker())
    resp = test_client.post("/api/v1/control/move", json={"x": 50})
    assert resp.status_code == 409
    assert "disabled while a print is active" in resp.json["error"]

def test_move_simulated_worker(test_client, monkeypatch):
    class SimWorker:
        latest = {"print_state": "standby"}
        def move_to(self, **kwargs):
            return True
    monkeypatch.setattr("api.server._worker", lambda: SimWorker())
    resp = test_client.post("/api/v1/control/move", json={"x": 120, "y": 80})
    assert resp.status_code == 200
    assert resp.json.get("simulated") is True

def test_move_simulated_blocked_by_safety(test_client, monkeypatch):
    class SafeWorker:
        latest = {"print_state": "standby"}
        def move_to(self, **kwargs):
            return False
    monkeypatch.setattr("api.server._worker", lambda: SafeWorker())
    resp = test_client.post("/api/v1/control/move", json={"x": -10, "y": 500})
    assert resp.status_code == 409
    assert "blocked by bed safety" in resp.json["error"]
