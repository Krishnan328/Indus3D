import pytest
import time
from digital_twin.thermal_model import ThermalModel

def test_thermal_model_initialization():
    model = ThermalModel()
    assert model._ext_heat_cycles == 0
    assert model._bed_heat_cycles == 0

def test_no_runaway_under_normal_conditions():
    model = ThermalModel()
    for i in range(10):
        snap = {
            "ext_temp": 20.0 + i * 2.0, "ext_target": 200.0, "ext_pwm": 1.0,
            "bed_temp": 20.0, "bed_target": 60.0
        }
        res = model.update(snap)
        assert not res["ext_runaway_flag"]

def test_ext_thermal_runaway_detection():
    model = ThermalModel()
    # High window so they don't expire during test
    model._RUNAWAY_WINDOW = 10.0 
    model._RUNAWAY_DELTA = 5.0
    
    # We need at least 10 items in history, and at least 5 in window
    for i in range(10):
        snap = {
            "ext_temp": 200.0 - (i * 1.0), # Temp is DROPPING 1 degree per tick
            "ext_target": 200.0,
            "ext_pwm": 1.0, # Heater is fully ON
            "bed_temp": 60.0, "bed_target": 60.0
        }
        res = model.update(snap)
    
    # After 10 ticks, temp dropped by 9 degrees, PWM is 1.0
    assert res["ext_runaway_flag"] is True

def test_no_runaway_when_pwm_low():
    model = ThermalModel()
    model._RUNAWAY_WINDOW = 10.0
    model._RUNAWAY_DELTA = 5.0
    
    for i in range(10):
        snap = {
            "ext_temp": 200.0 - (i * 1.0), # Temp is DROPPING
            "ext_target": 200.0,
            "ext_pwm": 0.0, # PWM is LOW, so cooling down is EXPECTED
            "bed_temp": 60.0, "bed_target": 60.0
        }
        res = model.update(snap)
    
    # Should NOT trigger runaway because PWM was low
    assert res["ext_runaway_flag"] is False

def test_heat_cycle_counting():
    model = ThermalModel()
    model.update({"ext_temp": 25, "ext_target": 0, "ext_pwm": 0, "bed_temp": 25, "bed_target": 0})
    assert model._ext_heat_cycles == 0
    model.update({"ext_temp": 200, "ext_target": 200, "ext_pwm": 1, "bed_temp": 25, "bed_target": 0})
    model.update({"ext_temp": 35, "ext_target": 0, "ext_pwm": 0, "bed_temp": 25, "bed_target": 0})
    assert model._ext_heat_cycles == 1
