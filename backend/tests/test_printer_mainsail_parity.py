import pytest
import time
from unittest.mock import MagicMock, patch
from api.server import app
from workers.telemetry_worker import TelemetryWorker

@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()

# ── Spoolman Proxy ────────────────────────────────────────────────────────────

def test_spoolman_proxy_url(client, monkeypatch):
    recorded_requests = []

    def mock_post(url, **kwargs):
        recorded_requests.append((url, kwargs))
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.text = '{"result": []}'
        mock_resp.headers = {"Content-Type": "application/json"}
        return mock_resp

    monkeypatch.setattr("requests.post", mock_post)

    resp = client.get("/api/v1/printer/spoolman/spools")
    assert resp.status_code == 200
    assert len(recorded_requests) == 1
    url, kwargs = recorded_requests[0]
    assert "/server/spoolman/proxy" in url
    assert kwargs.get("json", {}).get("path") == "/api/v1/spool"


# ── Bed Mesh Profiles ─────────────────────────────────────────────────────────

def test_bedmesh_profiles_get(client, monkeypatch):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "status": {
                "bed_mesh": {
                    "profile_name": "pei_sheet",
                    "profiles": {"pei_sheet": {"points": [[0.1, 0.2], [0.3, 0.4]]}},
                    "probed_matrix": [[0.1, 0.2]],
                    "mesh_matrix": [[0.15, 0.25]],
                }
            }
        }
    }
    monkeypatch.setattr("requests.get", lambda url, **kwargs: mock_resp)

    resp = client.get("/api/v1/printer/bedmesh/profiles")
    assert resp.status_code == 200
    data = resp.json
    assert data["profile_name"] == "pei_sheet"
    assert "pei_sheet" in data["profiles"]
    assert data["probed_matrix"] == [[0.1, 0.2]]
    assert data["mesh_matrix"] == [[0.15, 0.25]]


def test_bedmesh_profile_load(client, monkeypatch):
    recorded = []
    def mock_post(url, **kwargs):
        recorded.append((url, kwargs))
        m = MagicMock()
        m.ok = True
        m.status_code = 200
        return m

    monkeypatch.setattr("requests.post", mock_post)

    resp = client.post("/api/v1/printer/bedmesh/profile/load", json={"name": "pei_sheet"})
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"
    assert "Loaded profile pei_sheet" in resp.json["message"]
    assert len(recorded) == 1
    assert recorded[0][1]["params"]["script"] == "BED_MESH_PROFILE LOAD=pei_sheet"


def test_bedmesh_profile_save(client, monkeypatch):
    recorded = []
    def mock_post(url, **kwargs):
        recorded.append((url, kwargs))
        m = MagicMock()
        m.ok = True
        m.status_code = 200
        return m

    monkeypatch.setattr("requests.post", mock_post)

    resp = client.post("/api/v1/printer/bedmesh/profile/save", json={"name": "pei_sheet"})
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"
    assert "Saved profile pei_sheet" in resp.json["message"]
    assert len(recorded) == 1
    assert recorded[0][1]["params"]["script"] == "BED_MESH_PROFILE SAVE=pei_sheet"


def test_bedmesh_profile_remove(client, monkeypatch):
    recorded = []
    def mock_post(url, **kwargs):
        recorded.append((url, kwargs))
        m = MagicMock()
        m.ok = True
        m.status_code = 200
        return m

    monkeypatch.setattr("requests.post", mock_post)

    resp = client.delete("/api/v1/printer/bedmesh/profile/pei_sheet")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"
    assert "Removed profile pei_sheet" in resp.json["message"]
    assert len(recorded) == 1
    assert recorded[0][1]["params"]["script"] == "BED_MESH_PROFILE REMOVE=pei_sheet"


# ── Endstops ──────────────────────────────────────────────────────────────────

def test_endstops_query_success(client, monkeypatch):
    post_mock = MagicMock(ok=True, status_code=200)
    get_mock = MagicMock(
        ok=True,
        status_code=200,
        json=lambda: {"result": {"status": {"x": "open", "y": "TRIGGERED", "z": "open"}}}
    )

    monkeypatch.setattr("requests.post", lambda url, **kwargs: post_mock)
    monkeypatch.setattr("requests.get", lambda url, **kwargs: get_mock)

    resp = client.get("/api/v1/printer/endstops")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"
    assert resp.json["endstops"] == {"x": "open", "y": "TRIGGERED", "z": "open"}


def test_endstops_query_failure(client, monkeypatch):
    post_mock = MagicMock(ok=False, status_code=500)
    monkeypatch.setattr("requests.post", lambda url, **kwargs: post_mock)

    resp = client.get("/api/v1/printer/endstops")
    assert resp.status_code == 200
    assert resp.json["status"] == "unavailable"
    assert resp.json["endstops"] == {}


# ── System Stats ──────────────────────────────────────────────────────────────

def test_system_stats(client, monkeypatch):
    def mock_get(url, **kwargs):
        m = MagicMock(ok=True, status_code=200)
        if "proc_stats" in url:
            m.json.return_value = {
                "result": {
                    "cpu_temp": 48.5,
                    "system_cpu_usage": {"cpu": 12.4},
                    "system_memory": {"total": 4000000, "used": 2000000, "available": 2000000},
                    "network": {"wlan0": {"rx_bytes": 1000, "tx_bytes": 2000}},
                }
            }
        elif "system_info" in url:
            m.json.return_value = {
                "result": {
                    "system_info": {
                        "distribution": {"name": "Debian", "version": "12"},
                        "cpu_info": {"model": "ARMv8"},
                        "python": {"version": "3.11.2"},
                    }
                }
            }
        return m

    monkeypatch.setattr("requests.get", mock_get)

    resp = client.get("/api/v1/printer/system/stats")
    assert resp.status_code == 200
    data = resp.json
    assert data["status"] == "ok"
    stats = data["stats"]
    assert stats["cpu_temp"] == 48.5
    assert stats["cpu_usage"] == 12.4
    assert stats["memory"]["percent"] == 50.0
    assert "wlan0" in stats["network"]
    assert stats["system_info"]["distribution"]["name"] == "Debian"


# ── Files & Directory Management ──────────────────────────────────────────────

def test_files_list_with_and_without_path(client, monkeypatch):
    recorded = []
    def mock_get(url, **kwargs):
        recorded.append((url, kwargs))
        m = MagicMock(ok=True, status_code=200, text='{"result": []}')
        m.headers = {"Content-Type": "application/json"}
        return m

    monkeypatch.setattr("requests.get", mock_get)

    client.get("/api/v1/printer/files/list")
    assert len(recorded) == 1
    assert recorded[0][1]["params"] == {"root": "gcodes"}

    client.get("/api/v1/printer/files/list?path=calibration")
    assert len(recorded) == 2
    assert recorded[1][1]["params"] == {"root": "gcodes", "path": "calibration"}


def test_directory_create_and_delete(client, monkeypatch):
    recorded = []
    def mock_post(url, **kwargs):
        recorded.append(("POST", url, kwargs))
        m = MagicMock(ok=True, status_code=200, text='{"result": "ok"}')
        m.headers = {"Content-Type": "application/json"}
        return m

    def mock_delete(url, **kwargs):
        recorded.append(("DELETE", url, kwargs))
        m = MagicMock(ok=True, status_code=200, text='{"result": "ok"}')
        m.headers = {"Content-Type": "application/json"}
        return m

    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("requests.delete", mock_delete)

    resp_create = client.post("/api/v1/printer/files/directory", json={"path": "gcodes/benchies"})
    assert resp_create.status_code == 200
    assert recorded[-1][0] == "POST"
    assert recorded[-1][2]["params"]["path"] == "gcodes/benchies"

    resp_del = client.delete("/api/v1/printer/files/directory", json={"path": "gcodes/benchies"})
    assert resp_del.status_code == 200
    assert recorded[-1][0] == "DELETE"
    assert recorded[-1][2]["params"]["path"] == "gcodes/benchies"


def test_file_move(client, monkeypatch):
    recorded = []
    def mock_post(url, **kwargs):
        recorded.append((url, kwargs))
        m = MagicMock(ok=True, status_code=200, text='{"result": "ok"}')
        m.headers = {"Content-Type": "application/json"}
        return m

    monkeypatch.setattr("requests.post", mock_post)

    resp = client.post("/api/v1/printer/files/move", json={"source": "gcodes/a.gcode", "dest": "gcodes/b.gcode"})
    assert resp.status_code == 200
    assert len(recorded) == 1
    assert recorded[0][1]["json"] == {"source": "gcodes/a.gcode", "dest": "gcodes/b.gcode"}


# ── Telemetry Worker ──────────────────────────────────────────────────────────

def test_telemetry_worker_live_commands_and_preload():
    w = TelemetryWorker()
    assert w.live_commands.maxlen == 100

    # Test preloading gcode store
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {
        "result": {
            "gcode_store": [
                {"message": "G28", "time": 100.0, "type": "command"},
                {"message": "echo: bed leveled", "time": 101.0, "type": "response"},
            ]
        }
    }
    with patch.object(w._session, "get", return_value=mock_resp):
        w._preload_gcode_store()

    assert len(w.live_commands) == 2
    assert w.live_commands[0]["text"] == "G28"
    assert w.live_commands[1]["text"] == "echo: bed leveled"
