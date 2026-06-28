"""
config/cfg_parser.py
---------------------
Parses Klipper's printer.cfg (and optionally indus_overrides.cfg) into the
same profile dict that the rest of Indus3D expects.

Klipper cfg format:
    [section_name]
    key = value
    # comment

What we extract:
    [stepper_x/y/z]        → steps_per_mm, max velocity hints
    [extruder]             → nozzle_diameter, filament_diameter,
                             max_extrude_temp, pid_Kp/Ki/Kd, max_extrude_only_velocity
    [heater_bed]           → max_temp, pid_Kp/Ki/Kd
    [printer]              → max_velocity, max_accel, kinematics
    [stepper_z] position_max → bed Z height
    [bed_mesh]  mesh_min/max → bed XY size
    OR [stepper_x/y] position_max → bed XY size fallback

Handles:
    - Inline comments   (key = value  # comment)
    - [include filename] directives  (one level deep)
    - Missing sections  (falls back to sensible defaults)
    - Non-numeric values (skipped gracefully)
"""

import re
import os
import configparser
from typing import Optional


# ── Safe numeric helpers ──────────────────────────────────────────────────────

def _float(val: str, default: float) -> float:
    try:
        return float(val.split("#")[0].strip())
    except (ValueError, AttributeError):
        return default


def _int(val: str, default: int) -> int:
    try:
        return int(float(val.split("#")[0].strip()))
    except (ValueError, AttributeError):
        return default


# ── Klipper cfg reader ────────────────────────────────────────────────────────

def _read_klipper_cfg(cfg_path: str) -> dict:
    """
    Parse a Klipper .cfg file into a nested dict:
        { section_name: { key: value_string, ... }, ... }

    Handles [include relative/path.cfg] one level deep.
    Does NOT use configparser because Klipper allows duplicate section names
    and configparser chokes on them.
    """
    if not os.path.isfile(cfg_path):
        return {}

    base_dir = os.path.dirname(cfg_path)
    sections  = {}
    current   = None

    def _process_file(path):
        nonlocal current
        try:
            with open(path, "r", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return

        for line in lines:
            line = line.strip()

            # Skip blank / pure comment
            if not line or line.startswith("#"):
                continue

            # Include directive
            inc = re.match(r"^\[include\s+(.+?)\]$", line, re.I)
            if inc:
                inc_path = os.path.join(base_dir, inc.group(1).strip())
                if os.path.isfile(inc_path):
                    _process_file(inc_path)
                continue

            # Section header
            sec = re.match(r"^\[(.+?)\]$", line)
            if sec:
                current = sec.group(1).strip().lower()
                # Allow duplicate sections (e.g. two [temperature_sensor])
                # by appending a counter suffix
                if current in sections:
                    i = 2
                    while f"{current}__{i}" in sections:
                        i += 1
                    current = f"{current}__{i}"
                sections[current] = {}
                continue

            # Key = value
            if current is not None and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip().lower()
                val = val.split("#")[0].strip()   # strip inline comment
                sections[current][key] = val

    _process_file(cfg_path)
    return sections


# ── Override cfg (indus_overrides.cfg) ───────────────────────────────────────

def _read_overrides(overrides_path: str) -> dict:
    """Simple configparser read — indus_overrides.cfg is well-formed."""
    cfg = configparser.ConfigParser()
    cfg.optionxform = str   # preserve case
    if os.path.isfile(overrides_path):
        cfg.read(overrides_path)
    section = dict(cfg["indus3d"]) if "indus3d" in cfg else {}
    return section


# ── Profile builder ───────────────────────────────────────────────────────────

def build_profile(cfg_path: str,
                  overrides_path: Optional[str] = None) -> dict:
    """
    Main entry point.  Returns a profile dict identical in shape to
    the old printer_profile.json so the rest of the codebase is unchanged.

    cfg_path         — absolute path to printer.cfg on the Pi (or a local copy)
    overrides_path   — absolute path to indus_overrides.cfg
    """

    kc = _read_klipper_cfg(cfg_path)
    ov = _read_overrides(overrides_path) if overrides_path else {}

    # ── [printer] ─────────────────────────────────────────────────────────────
    pr          = kc.get("printer", {})
    kinematics  = pr.get("kinematics", "cartesian").strip('"').strip("'")
    max_vel     = _float(pr.get("max_velocity", "300"), 300.0)
    max_accel   = _float(pr.get("max_accel", "3000"), 3000.0)

    # ── Bed size ──────────────────────────────────────────────────────────────
    # Prefer [bed_mesh] mesh_min / mesh_max
    bm          = kc.get("bed_mesh", {})
    origin_center = kinematics in ("delta", "polar")

    if bm.get("mesh_max") and bm.get("mesh_min"):
        try:
            mesh_max = [float(v) for v in bm["mesh_max"].split(",")]
            mesh_min = [float(v) for v in bm["mesh_min"].split(",")]
            bed_x    = mesh_max[0] - mesh_min[0]
            bed_y    = mesh_max[1] - mesh_min[1]
        except Exception:
            bed_x, bed_y = 300.0, 300.0
    else:
        # Fallback: stepper position_max
        sx   = kc.get("stepper_x", {})
        sy   = kc.get("stepper_y", {})
        bed_x = _float(sx.get("position_max", "300"), 300.0)
        bed_y = _float(sy.get("position_max", "300"), 300.0)

    sz    = kc.get("stepper_z", {})
    bed_z = _float(sz.get("position_max", "400"), 400.0)

    # ── Stepper steps/mm ──────────────────────────────────────────────────────
    sx_r = kc.get("stepper_x", {})
    sy_r = kc.get("stepper_y", {})
    sz_r = kc.get("stepper_z", {})

    steps_x = _float(sx_r.get("rotation_distance", "0"), 0)
    steps_y = _float(sy_r.get("rotation_distance", "0"), 0)
    steps_z = _float(sz_r.get("rotation_distance", "0"), 0)

    # Convert rotation_distance → steps/mm if full_steps_per_rotation & microsteps present
    def _steps_per_mm(section: dict, default: float) -> float:
        rd = _float(section.get("rotation_distance", "0"), 0)
        if rd <= 0:
            return default
        fs = _float(section.get("full_steps_per_rotation", "200"), 200)
        ms = _float(section.get("microsteps", "16"), 16)
        return round((fs * ms) / rd, 2)

    # ── [extruder] ────────────────────────────────────────────────────────────
    ext          = kc.get("extruder", {})
    nozzle_dia   = _float(ext.get("nozzle_diameter",   "0.4"),  0.4)
    fil_dia      = _float(ext.get("filament_diameter", "1.75"), 1.75)
    ext_max_temp = _float(ext.get("max_temp",          "300"),  300.0)
    ext_pid_kp   = _float(ext.get("pid_kp",  "21.0"), 21.0)
    ext_pid_ki   = _float(ext.get("pid_ki",  "1.08"), 1.08)
    ext_pid_kd   = _float(ext.get("pid_kd",  "100.0"), 100.0)
    steps_e      = _steps_per_mm(ext, 415.0)

    # ── [heater_bed] ──────────────────────────────────────────────────────────
    hb           = kc.get("heater_bed", {})
    bed_max_temp = _float(hb.get("max_temp", "120"), 120.0)
    bed_pid_kp   = _float(hb.get("pid_kp",  "40.0"), 40.0)
    bed_pid_ki   = _float(hb.get("pid_ki",  "4.0"),  4.0)
    bed_pid_kd   = _float(hb.get("pid_kd",  "100.0"), 100.0)

    # ── Printer name ──────────────────────────────────────────────────────────
    # Check for a [printer] name field or fall back
    printer_name = pr.get("name", "Klipper Printer").strip('"').strip("'")

    # ── Overrides ─────────────────────────────────────────────────────────────
    mr_ip   = ov.get("moonraker_ip",   "100.88.38.105")
    mr_port = _int(ov.get("moonraker_port", "7125"), 7125)

    profile = {
        "printer_name": printer_name,
        "kinematics":   kinematics,

        "bed": {
            "size_x_mm":    round(bed_x, 1),
            "size_y_mm":    round(bed_y, 1),
            "size_z_mm":    round(bed_z, 1),
            "origin_center": origin_center,
        },

        "motion": {
            "max_velocity_mm_s":  max_vel,
            "max_accel_mm_s2":    max_accel,
            "steps_per_mm_x":     _steps_per_mm(kc.get("stepper_x", {}), 80.0),
            "steps_per_mm_y":     _steps_per_mm(kc.get("stepper_y", {}), 80.0),
            "steps_per_mm_z":     _steps_per_mm(kc.get("stepper_z", {}), 400.0),
            "steps_per_mm_e":     steps_e,
        },

        "hotend": {
            "nozzle_diameter_mm":  nozzle_dia,
            "filament_diameter_mm": fil_dia,
            "max_temp_c":          ext_max_temp,
            "pid_kp":              ext_pid_kp,
            "pid_ki":              ext_pid_ki,
            "pid_kd":              ext_pid_kd,
        },

        "bed_heater": {
            "max_temp_c": bed_max_temp,
            "pid_kp":     bed_pid_kp,
            "pid_ki":     bed_pid_ki,
            "pid_kd":     bed_pid_kd,
        },

        "print": {
            "layer_height_mm":          _float(ov.get("layer_height_mm",          "0.2"),  0.2),
            "line_width_mm":            _float(ov.get("line_width_mm",            "0.4"),  0.4),
            "linear_advance_k":         _float(ov.get("linear_advance_k",         "0.04"), 0.04),
            "max_volumetric_flow_mm3_s": _float(ov.get("max_volumetric_flow_mm3s", "12.0"), 12.0),
        },

        "moonraker": {
            "ip":   mr_ip,
            "port": mr_port,
        },

        "alerts": {
            "lag_magnitude_warn_mm":    _float(ov.get("lag_magnitude_warn_mm",    "0.8"),  0.8),
            "stress_score_warn":        _float(ov.get("stress_score_warn",        "0.5"),  0.5),
            "ext_heat_cycles_warn":     _float(ov.get("ext_heat_cycles_warn",     "500"),  500),
            "bed_heat_cycles_warn":     _float(ov.get("bed_heat_cycles_warn",     "500"),  500),
            "thermal_runaway_delta_c":  _float(ov.get("thermal_runaway_delta_c",  "15.0"), 15.0),
            "thermal_runaway_window_s": _float(ov.get("thermal_runaway_window_s", "5.0"),  5.0),
        },
    }

    return profile


# ── Debug helper ─────────────────────────────────────────────────────────────

def profile_summary(profile: dict) -> str:
    b  = profile["bed"]
    m  = profile["motion"]
    h  = profile["hotend"]
    hb = profile["bed_heater"]
    mr = profile["moonraker"]
    return (
        f"\n{'─'*50}\n"
        f"  Printer  : {profile['printer_name']}\n"
        f"  Kinematics: {profile['kinematics']}\n"
        f"  Bed       : {b['size_x_mm']} × {b['size_y_mm']} × {b['size_z_mm']} mm\n"
        f"  Nozzle    : {h['nozzle_diameter_mm']} mm  Filament: {h['filament_diameter_mm']} mm\n"
        f"  Ext PID   : kP={h['pid_kp']}  kI={h['pid_ki']}  kD={h['pid_kd']}\n"
        f"  Bed PID   : kP={hb['pid_kp']}  kI={hb['pid_ki']}  kD={hb['pid_kd']}\n"
        f"  Max vel   : {m['max_velocity_mm_s']} mm/s   Max accel: {m['max_accel_mm_s2']} mm/s²\n"
        f"  Steps/mm  : X={m['steps_per_mm_x']}  Y={m['steps_per_mm_y']}"
        f"  Z={m['steps_per_mm_z']}  E={m['steps_per_mm_e']}\n"
        f"  Moonraker : {mr['ip']}:{mr['port']}\n"
        f"{'─'*50}"
    )


if __name__ == "__main__":
    import sys
    cfg_path      = sys.argv[1] if len(sys.argv) > 1 else "printer.cfg"
    override_path = sys.argv[2] if len(sys.argv) > 2 else "indus_overrides.cfg"
    p = build_profile(cfg_path, override_path)
    print(profile_summary(p))
    import json
    print(json.dumps(p, indent=2))
