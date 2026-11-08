"""
tests/test_thermodynamic_clog.py
----------------------------------
Unit tests for calc_thermodynamic_mass_flow() (Group O).
Covers: healthy flow, clog scenario, zero-flow guard, edge cases.
"""

import pytest
from digital_twin.control_models import calc_thermodynamic_mass_flow


class TestThermodynamicMassFlow:
    def test_healthy_flow_no_clog(self):
        """High PWM duty cycle with low commanded flow → healthy, no clog."""
        m_dot, clog, ratio = calc_thermodynamic_mass_flow(
            extruder_power_frac=0.80,
            heater_rated_w=40.0,
            t_nozzle_c=215.0,
            t_ambient_c=25.0,
            volumetric_flow_cmd_mm3_s=5.0,
        )
        assert not clog, "Healthy high-PWM flow should NOT trigger clog"
        assert ratio > 0.45, f"Expected ratio > 0.45, got {ratio}"
        assert m_dot > 0.0

    def test_clog_low_pwm_high_flow(self):
        """Low PWM + high commanded flow → clog suspected."""
        m_dot, clog, ratio = calc_thermodynamic_mass_flow(
            extruder_power_frac=0.05,   # heater barely on — filament not melting
            heater_rated_w=40.0,
            t_nozzle_c=215.0,
            t_ambient_c=25.0,
            volumetric_flow_cmd_mm3_s=15.0,   # fast extrusion commanded
        )
        assert clog, f"Low PWM + high flow should trigger clog (ratio={ratio})"
        assert ratio < 0.45

    def test_zero_flow_cmd_no_clog(self):
        """When commanded flow is below threshold, clog check skipped."""
        _m, clog, ratio = calc_thermodynamic_mass_flow(
            extruder_power_frac=0.10,
            heater_rated_w=40.0,
            t_nozzle_c=215.0,
            t_ambient_c=25.0,
            volumetric_flow_cmd_mm3_s=1.0,  # below min_flow_cmd_mm3_s=3.0
        )
        assert not clog, "Below-threshold flow should not flag clog"
        assert ratio == 1.0

    def test_zero_heater_power_guard(self):
        """heater_rated_w=0 should return safe defaults without division error."""
        m_dot, clog, ratio = calc_thermodynamic_mass_flow(
            extruder_power_frac=0.80,
            heater_rated_w=0.0,
            t_nozzle_c=215.0,
            t_ambient_c=25.0,
            volumetric_flow_cmd_mm3_s=10.0,
        )
        assert not clog
        assert m_dot == 0.0
        assert ratio == 1.0

    def test_ambient_above_nozzle_guard(self):
        """t_ambient >= t_nozzle should return safe defaults."""
        m_dot, clog, ratio = calc_thermodynamic_mass_flow(
            extruder_power_frac=0.80,
            heater_rated_w=40.0,
            t_nozzle_c=20.0,     # below ambient — sensor error
            t_ambient_c=25.0,
            volumetric_flow_cmd_mm3_s=10.0,
        )
        assert not clog
        assert m_dot == 0.0

    def test_return_tuple_types(self):
        """Return types must be (float, bool, float)."""
        result = calc_thermodynamic_mass_flow(
            extruder_power_frac=0.5,
            heater_rated_w=40.0,
            t_nozzle_c=210.0,
            t_ambient_c=25.0,
            volumetric_flow_cmd_mm3_s=8.0,
        )
        assert isinstance(result[0], float)
        assert isinstance(result[1], bool)
        assert isinstance(result[2], float)

    def test_thermal_ratio_clamped_above_one(self):
        """Thermal ratio must not exceed 2.0 (clamped)."""
        _m, _clog, ratio = calc_thermodynamic_mass_flow(
            extruder_power_frac=1.0,   # full power
            heater_rated_w=40.0,
            t_nozzle_c=215.0,
            t_ambient_c=25.0,
            volumetric_flow_cmd_mm3_s=0.01,  # tiny commanded flow
        )
        assert ratio <= 2.0
