import pytest
import math
from digital_twin import control_models


def test_non_newtonian_melt_pressure():
    # Zero flow rate returns 0.0
    assert control_models.calc_non_newtonian_melt_pressure(0.0, 210.0) == 0.0
    assert control_models.calc_non_newtonian_melt_pressure(-5.0, 210.0) == 0.0

    # Normal PLA extrusion: 10 mm³/s at 210°C with 0.4mm nozzle
    dp_nominal = control_models.calc_non_newtonian_melt_pressure(10.0, 210.0)
    # Physical backpressure is typically 1 to 15 MPa (1e6 to 15e6 Pa)
    assert 5e5 < dp_nominal < 2e7

    # Cold extrusion (190°C) should have significantly higher pressure due to Arrhenius viscosity
    dp_cold = control_models.calc_non_newtonian_melt_pressure(10.0, 190.0)
    assert dp_cold > dp_nominal

    # Higher flow rate (25 mm³/s) should increase pressure
    dp_high_q = control_models.calc_non_newtonian_melt_pressure(25.0, 210.0)
    assert dp_high_q > dp_nominal


def test_extruder_motor_current_and_clog_detection():
    # Friction-only baseline current when pressure is 0
    i_base = control_models.calc_extruder_motor_current(0.0)
    assert 0.02 < i_base < 0.25  # ~44 mA friction baseline

    # Active extrusion with 4 MPa backpressure
    i_extruding = control_models.calc_extruder_motor_current(4e6)
    assert i_extruding > i_base
    assert 0.2 < i_extruding < 1.0  # realistic pancake stepper current

    # Clog and stripping detection
    status_norm, ratio_norm = control_models.detect_nozzle_clog_or_strip(0.35, 0.35)
    assert status_norm == "NORMAL"
    assert ratio_norm == 1.0

    status_clog, ratio_clog = control_models.detect_nozzle_clog_or_strip(0.60, 0.35)
    assert status_clog == "CLOG_WARNING"
    assert ratio_clog > 1.35

    status_strip, ratio_strip = control_models.detect_nozzle_clog_or_strip(0.12, 0.35)
    assert status_strip == "STRIPPING_WARNING"
    assert ratio_strip < 0.60


def test_sintering_healing_degree():
    # Cold bead below glass transition produces zero healing
    t_freeze, dh, strength = control_models.calc_sintering_healing_degree(
        t_bead_initial_c=50.0,
        t_substrate_c=40.0,
        t_ambient_c=25.0,
        actual_layer_time_s=15.0,
        t_glass_c=60.0
    )
    assert t_freeze == 0.0
    assert dh == 0.0
    assert strength == 0.0

    # Normal deposition: 210°C on 60°C bed
    t_freeze, dh, strength = control_models.calc_sintering_healing_degree(
        t_bead_initial_c=210.0,
        t_substrate_c=60.0,
        t_ambient_c=25.0,
        actual_layer_time_s=15.0,
        fan_pwm=100,
        t_glass_c=55.0
    )
    assert t_freeze > 0.05
    assert strength > 0.0
    assert strength <= 1.0

    # Excessive cooling (fan 255) decreases freeze time compared to low fan (30)
    t_freeze_fast, _, _ = control_models.calc_sintering_healing_degree(
        210.0, 60.0, 25.0, 15.0, fan_pwm=255, t_glass_c=55.0
    )
    t_freeze_slow, _, _ = control_models.calc_sintering_healing_degree(
        210.0, 60.0, 25.0, 15.0, fan_pwm=30, t_glass_c=55.0
    )
    assert t_freeze_fast < t_freeze_slow


def test_graetz_undercooling():
    # Zero or negative flow has zero undercooling
    gz, dt = control_models.calc_graetz_undercooling(0.0)
    assert gz == 0.0 and dt == 0.0

    # Low flow (2 mm³/s) has low Gz and no undercooling
    gz_low, dt_low = control_models.calc_graetz_undercooling(2.0)
    assert gz_low < 1.0
    assert dt_low == 0.0

    # High flow (20 mm³/s) has high Gz and positive undercooling
    gz_high, dt_high = control_models.calc_graetz_undercooling(20.0)
    assert gz_high > 1.5
    assert dt_high > 1.0
    assert dt_high <= 16.0


def test_repulsive_force_warpage():
    # Insignificant reaction force
    w_h, warn = control_models.calc_repulsive_force_warpage(0.02)
    assert w_h == 0.0 and warn is False

    # Moderate force below warning threshold (0.5 N)
    w_h_mid, warn_mid = control_models.calc_repulsive_force_warpage(0.5, nominal_layer_height_mm=0.2)
    assert w_h_mid > 0.2
    assert warn_mid is False

    # Excessive force (2.5 N) indicating nozzle plunging into warped corner
    w_h_high, warn_high = control_models.calc_repulsive_force_warpage(2.5, nominal_layer_height_mm=0.2)
    assert w_h_high >= 0.35
    assert warn_high is True


def test_mass_adaptive_shaper():
    # Zero mass added
    f_new, zeta, d2 = control_models.calc_mass_adaptive_shaper_frequency(
        f_baseline_hz=45.0,
        bed_mass_g=800.0,
        part_mass_g=0.0,
        zeta_baseline=0.08
    )
    assert math.isclose(f_new, 45.0, abs_tol=0.2)
    assert math.isclose(d2, 0.5 / 45.0, abs_tol=1e-3)

    # 400g part printed on 800g bed (mass ratio 1.5)
    f_heavy, zeta_heavy, d2_heavy = control_models.calc_mass_adaptive_shaper_frequency(
        f_baseline_hz=45.0,
        bed_mass_g=800.0,
        part_mass_g=400.0,
        zeta_baseline=0.08
    )
    # Frequency drops by ~ sqrt(800 / 1200) = sqrt(2/3) ≈ 0.816 -> 45 * 0.816 ≈ 36.7 Hz
    assert 34.0 < f_heavy < 38.0
    assert zeta_heavy > 0.08
    assert d2_heavy > d2  # Longer impulse spacing for lower frequency


def test_surface_roughness_and_perimeter_optimization():
    # Roughness increases with layer height
    ra_012 = control_models.calc_surface_roughness_ra(0.12, 50.0, 210.0)
    ra_028 = control_models.calc_surface_roughness_ra(0.28, 50.0, 210.0)
    assert ra_028 > ra_012

    # Higher speed slightly increases roughness
    ra_slow = control_models.calc_surface_roughness_ra(0.2, 30.0, 210.0)
    ra_fast = control_models.calc_surface_roughness_ra(0.2, 90.0, 210.0)
    assert ra_fast > ra_slow

    # Optimization: if current Ra is higher than target, speed is trimmed
    v_opt, t_opt, ra_opt = control_models.calc_optimal_perimeter_parameters(
        layer_height_mm=0.2,
        target_ra_um=8.0,
        t_nominal_c=205.0,
        v_nominal_mm_s=80.0
    )
    assert v_opt < 80.0
    assert ra_opt < control_models.calc_surface_roughness_ra(0.2, 80.0, 205.0)
