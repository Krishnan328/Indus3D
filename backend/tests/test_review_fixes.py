"""Regression tests for the code-review fixes (printer routes, models, QC)."""
import time
from unittest import mock

import pytest

from api.routes.printer import _is_safe_gcode
from digital_twin import control_models as cm
from digital_twin.quality_controller import QualityController


# ── G-code allowlist ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("cmd", [
    "G1 X10 Y10 F3000", "M104 S200", "SET_PRESSURE_ADVANCE ADVANCE=0.04",
    "G91\nG1 X5 F3000\nG90", "M220 S90", "m117 hello",
])
def test_safe_gcode_allowed(cmd):
    assert _is_safe_gcode(cmd)


@pytest.mark.parametrize("cmd", [
    "G90\nRUN_SHELL_COMMAND CMD=reboot",   # smuggled second line
    "M104 S0\r\nSHUTDOWN_NOW",              # CRLF smuggling
    "M122",                                  # bare "M1" prefix used to admit this
    "G20",                                   # bare "G2" prefix used to admit this
    "G1X10",                                 # not a whole-token command
    "", "   ", None,
])
def test_safe_gcode_rejected(cmd):
    assert not _is_safe_gcode(cmd)


# ── Config save no longer crashes on the diff ─────────────────────────────────
def test_config_save_builds_diff_and_uploads():
    from api.server import app
    old = mock.Mock(ok=True, text="a: 1\n")
    up = mock.Mock(text="{}", status_code=200)
    with mock.patch("api.routes.printer.requests.get", return_value=old), \
         mock.patch("api.routes.printer.requests.post", return_value=up) as post, \
         mock.patch("db.models.get_connection") as conn:
        r = app.test_client().post("/api/v1/printer/config/printer.cfg", data="a: 2\n")
    assert r.status_code == 200
    assert post.called
    diff = conn.return_value.execute.call_args[0][1][3]
    assert "-a: 1" in diff and "+a: 2" in diff


def test_config_path_traversal_rejected():
    from api.server import app
    r = app.test_client().get("/api/v1/printer/config/../secret")
    assert r.status_code in (400, 404)


# ── Models ────────────────────────────────────────────────────────────────────
def test_roughness_is_continuous_at_zero_angle():
    flat = cm.calc_surface_roughness_ra(0.2, 40.0, 200.0, 0.0)
    tilt = cm.calc_surface_roughness_ra(0.2, 40.0, 200.0, 0.1)
    assert abs(tilt - flat) < 0.1
    assert cm.calc_surface_roughness_ra(0.2, 40.0, 200.0, 60.0) > flat


def test_sintering_healing_decreases_with_cold_bead():
    hot = cm.calc_sintering_healing_degree(230.0, 60.0, 25.0, 20.0)[1]
    cool = cm.calc_sintering_healing_degree(130.0, 60.0, 25.0, 20.0)[1]
    assert hot >= cool


# ── Quality controller ────────────────────────────────────────────────────────
def test_flow_curve_factor_does_not_compound():
    qc = QualityController()
    ext = {"is_extruding": True, "expected_flow_mm3_s": 5.0, "flow_ratio": 1.0 - 0.06,
           "curvature_theta": 0.3}
    seen = []
    for i in range(4):
        qc._last_flow_t = 0
        qc._flow_control(ext, time.time())
        seen.append(qc._flow_cmd)
    # Feedback pushes up, the curve factor is a bounded constant offset:
    # the command must not collapse toward the floor.
    assert min(seen) > 90.0


def test_flow_step_is_bounded():
    qc = QualityController()
    ext = {"is_extruding": True, "expected_flow_mm3_s": 5.0, "flow_ratio": 0.5}
    qc._last_flow_t = 0
    qc._flow_control(ext, time.time())
    assert abs(qc._flow_cmd - 100.0) <= 5.0 + 1e-6
