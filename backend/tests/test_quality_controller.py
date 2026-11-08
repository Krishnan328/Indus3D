import pytest
import time
from digital_twin.quality_controller import QualityController, FLOW_DEADBAND, SPEED_DEADBAND, FLOW_MAX, FLOW_MIN

def test_quality_controller_not_printing():
    qc = QualityController()
    qc.auto_pilot = False
    cmds = qc.update({"print_state": "idle"}, {}, {}, {})
    assert len(cmds) == 0
    assert qc.active["enabled"] is False
    assert qc._flow_cmd == 100.0
    assert qc._speed_cmd == 100.0

def test_flow_control_under_extrusion():
    qc = QualityController()
    qc.auto_pilot = True
    qc._shaper_loaded = True 
    ext_data = {
        "is_extruding": True,
        "expected_flow_mm3_s": 5.0,
        "flow_ratio": 0.8  
    }
    qc._last_flow_t = 0
    cmds = qc.update({"print_state": "printing"}, {}, {}, ext_data)
    m221_cmds = [c for c in cmds if c.startswith("M221")]
    assert len(m221_cmds) == 1, f"Commands returned: {cmds}, flow_cmd: {qc._flow_cmd}"

def test_flow_control_over_extrusion():
    qc = QualityController()
    qc.auto_pilot = True
    qc._shaper_loaded = True
    ext_data = {
        "is_extruding": True,
        "expected_flow_mm3_s": 5.0,
        "flow_ratio": 1.2
    }
    qc._last_flow_t = 0
    cmds = qc.update({"print_state": "printing"}, {}, {}, ext_data)
    assert qc._flow_cmd < 100.0

def test_flow_deadband_respect():
    qc = QualityController()
    qc.auto_pilot = True
    qc._shaper_loaded = True
    ext_data = {
        "is_extruding": True,
        "expected_flow_mm3_s": 5.0,
        "flow_ratio": 1.0 - (FLOW_DEADBAND / 2)
    }
    qc._last_flow_t = 0
    cmds = qc.update({"print_state": "printing"}, {}, {}, ext_data)
    assert not any(c.startswith("M221") for c in cmds)
    assert qc._flow_cmd == 100.0

def test_speed_control_high_lag():
    qc = QualityController()
    qc.auto_pilot = True
    qc._shaper_loaded = True
    kin_data = {
        "lag_magnitude_mm": SPEED_DEADBAND + 1.0
    }
    qc._last_speed_t = 0
    cmds = qc.update({"print_state": "printing"}, kin_data, {}, {})
    assert qc._speed_cmd < 100.0

def test_autopilot_persistence():
    qc = QualityController()
    qc.auto_pilot = True
    assert qc.active["enabled"] is True
    # Test that a new instance loads the persisted setting
    qc2 = QualityController()
    assert qc2.auto_pilot is True
    assert qc2.active["enabled"] is True
    # Toggle off
    qc.auto_pilot = False
    assert qc.active["enabled"] is False
    qc3 = QualityController()
    assert qc3.auto_pilot is False

def test_dynamic_temp_safety_clamp():
    qc = QualityController()
    qc.auto_pilot = True
    qc._shaper_loaded = True
    qc._last_dynamic_t = 0
    # Simulate high flow and huge temp error that could cause runaway
    snap = {
        "print_state": "printing",
        "ext_target": 210.0,
        "ext_temp": 180.0,
        "live_z": 2.0,
        "velocity": 120.0
    }
    ext_data = {
        "is_extruding": True,
        "avg_flow_mm3_s": 20.0,
        "expected_flow_mm3_s": 20.0,
        "flow_ratio": 1.0
    }
    kin_data = {"live_x": 100.0, "live_y": 100.0, "stress_score": {"X": 0.2, "Y": 0.2}}
    cmds = qc.update(snap, kin_data, {"bed_temp": 60.0}, ext_data)
    # Target was 210°C; commanded temp must never exceed target + 12°C = 222°C
    temp_cmds = [c for c in cmds if c.startswith("M104")]
    if temp_cmds:
        temp_val = float(temp_cmds[0].split("S")[1])
        assert temp_val <= 222.0
        assert temp_val >= 200.0

