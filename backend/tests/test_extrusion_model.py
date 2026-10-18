import pytest
import time
from digital_twin.extrusion_model import ExtrusionModel

def test_initialization():
    em = ExtrusionModel()
    assert em._filament_consumed_mm == 0.0

def test_extrusion_calculations():
    em = ExtrusionModel()
    
    # Simulate a move
    # area is about 0.4 * 0.2 approx 0.08 mm^2
    # dt will be ~0 (since time.time() runs fast), so we need to mock time
    pass

def test_under_extrusion(monkeypatch):
    em = ExtrusionModel()
    
    start = time.time()
    def mock_time(): return start
    monkeypatch.setattr(time, "time", mock_time)
    
    em.update({"cmd_e": 0.0, "velocity": 0.0})
    
    # Advance time by 0.1s
    start += 0.1
    
    # 20 mm/s velocity. Expected flow = 20 * ~0.08 = ~1.6 mm3/s
    # Flow ratio = actual / expected
    # Let's provide 0 E delta, which means 0 actual flow.
    # So ratio = 0 / 1.6 = 0
    # This should flag under_extrusion
    res = em.update({"cmd_e": 0.001, "velocity": 20.0}) # Tiny E to make is_extruding = True
    
    assert res["is_extruding"] is True
    assert res["under_extrusion_flag"] is True
    assert res["over_extrusion_flag"] is False

def test_over_extrusion(monkeypatch):
    em = ExtrusionModel()
    
    start = time.time()
    def mock_time(): return start
    monkeypatch.setattr(time, "time", mock_time)
    
    em.update({"cmd_e": 0.0, "velocity": 0.0})
    start += 0.1
    
    # We provide a massive E delta.
    # 10 mm of filament in 0.1s = 100 mm/s feed rate!
    # Actual flow = 100 * 2.4 = 240 mm3/s
    # Expected flow = 20 * ~0.08 = ~1.6 mm3/s
    # Ratio >> 1.25
    res = em.update({"cmd_e": 10.0, "velocity": 20.0})
    
    assert res["is_extruding"] is True
    assert res["under_extrusion_flag"] is False
    assert res["over_extrusion_flag"] is True

def test_no_flags_on_travel_moves(monkeypatch):
    em = ExtrusionModel()
    start = time.time()
    def mock_time(): return start
    monkeypatch.setattr(time, "time", mock_time)
    
    em.update({"cmd_e": 0.0, "velocity": 0.0})
    start += 0.1
    
    # High velocity, but no E delta
    res = em.update({"cmd_e": 0.0, "velocity": 100.0})
    
    assert res["is_extruding"] is False
    assert res["under_extrusion_flag"] is False
    assert res["over_extrusion_flag"] is False
