import pytest
import workers
from workers.simulator import SimulatedTelemetryWorker
from api.server import app

def test_sim_m112_shutdown_and_firmware_restart():
    sim = SimulatedTelemetryWorker()
    sim._klippy_state = "ready"
    sim._handle_cmd("M112")
    assert sim._klippy_state == "shutdown"
    assert sim._klippy_connected is False
    assert "shutdown" in sim._klippy_state_message.lower()

    sim._handle_cmd("FIRMWARE_RESTART")
    assert sim._klippy_state == "ready"
    assert sim._klippy_connected is True
    assert sim._klippy_state_message == ""

def test_printer_info_and_restart_endpoints(monkeypatch):
    sim = SimulatedTelemetryWorker()
    monkeypatch.setattr(workers, "_active_worker", sim)
    client = app.test_client()
    res = client.get("/api/v1/printer/info")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("state") == "ready"
    assert data.get("klippy_connected") is True

    res = client.post("/api/v1/printer/firmware_restart")
    assert res.status_code == 200
    assert res.get_json().get("status") == "ok"

def test_set_temperature_endpoint(monkeypatch):
    sim = SimulatedTelemetryWorker()
    monkeypatch.setattr(workers, "_active_worker", sim)
    client = app.test_client()

    # Test single heater
    res = client.post("/api/v1/printer/temperature", json={"heater": "extruder", "target": 215})
    assert res.status_code == 200
    assert sim._ext.target == 215.0

    res = client.post("/api/v1/printer/temperature", json={"heater": "bed", "target": 65})
    assert res.status_code == 200
    assert sim._bed.target == 65.0

    # Test dual heater preheat
    res = client.post("/api/v1/printer/temperature", json={"extruder": 240, "bed": 80})
    assert res.status_code == 200
    assert sim._ext.target == 240.0
    assert sim._bed.target == 80.0

    # Test turning off heaters
    res = client.post("/api/v1/printer/temperature", json={"extruder": 0, "bed": 0})
    assert res.status_code == 200
    assert sim._ext.target == 0.0
    assert sim._bed.target == 0.0

def test_safe_gcode_validation():
    from api.routes.printer import _is_safe_gcode

    # Multiline extrusion/retraction scripts
    assert _is_safe_gcode("M83\nG1 E10 F300\nM82") is True
    assert _is_safe_gcode("M83\nG1 E-10 F300\nM82") is True

    # User macros
    assert _is_safe_gcode("NEBULA_LOAD_FILAMENT") is True
    assert _is_safe_gcode("NOZZLE_WIPE") is True
    assert _is_safe_gcode("PRINT_START BED=60 EXTRUDER=210") is True

    # Bed leveling and probing routines
    assert _is_safe_gcode("BED_SCREWS_ADJUST") is True
    assert _is_safe_gcode("SCREWS_TILT_CALCULATE") is True
    assert _is_safe_gcode("BED_MESH_CLEAR") is True
    assert _is_safe_gcode("PROBE_CALIBRATE") is True
    assert _is_safe_gcode("QUERY_ENDSTOPS") is True
    assert _is_safe_gcode("M119") is True

    # Stepper control and overrides
    assert _is_safe_gcode("M84") is True
    assert _is_safe_gcode("M220 S120") is True
    assert _is_safe_gcode("M221 S95") is True
    assert _is_safe_gcode("M106 S128") is True
    assert _is_safe_gcode("M107") is True

    # Shell injection rejections
    assert _is_safe_gcode("G28 | ls") is False
    assert _is_safe_gcode("G28 && cat /etc/passwd") is False
    assert _is_safe_gcode("G28; `reboot`") is False
    assert _is_safe_gcode("G28 $(whoami)") is False
    assert _is_safe_gcode("") is False
    assert _is_safe_gcode(None) is False


def test_device_temperatures_parsing():
    from workers.telemetry_worker import TelemetryWorker
    from digital_twin.state import printer_state

    worker = TelemetryWorker()
    raw_status = {
        "toolhead": {"position": [0, 0, 0, 0]},
        "temperature_sensor EBB36": {"temperature": 41.6},
        "temperature_sensor btt_eddy_mcu": {"temperature": 42.1},
        "temperature_probe btt_eddy": {"temperature": 41.2},
    }
    worker._process_data(raw_status)
    snap = printer_state.snapshot()
    devs = snap.get("device_temperatures", {})

    assert "EBB36" in devs
    assert devs["EBB36"]["temperature"] == 41.6
    assert devs["EBB36"]["type"] == "temperature_sensor"

    assert "btt_eddy_mcu" in devs
    assert devs["btt_eddy_mcu"]["temperature"] == 42.1

    assert "btt_eddy" in devs
    assert devs["btt_eddy"]["temperature"] == 41.2

