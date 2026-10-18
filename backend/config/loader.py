"""
config/loader.py
-----------------
Loads the printer profile in priority order:
  1. INDUS_SIM_PROFILE env var (set by main.py --profile flag)
  2. Fetch printer.cfg live from Moonraker API
  3. Local printer.cfg (common Klipper paths)
  4. printer_profile.json fallback
"""

import logging
import os, json, tempfile, requests
from config.settings import settings

_HERE = os.path.dirname(os.path.abspath(__file__))
_OVERRIDES_PATH = os.path.join(_HERE, "indus_overrides.cfg")
_FALLBACK_JSON  = os.path.join(_HERE, "printer_profile.json")

_LOCAL_CFG_CANDIDATES = [
    os.path.expanduser("~/printer_data/config/printer.cfg"),
    os.path.expanduser("~/klipper_config/printer.cfg"),
    "/home/pi/printer_data/config/printer.cfg",
    "/home/pi/klipper_config/printer.cfg",
    os.path.join(_HERE, "printer.cfg"),
]

_cache: dict = {}


def _fetch_cfg_from_moonraker(ip, port):
    try:
        res = requests.get(f"http://{ip}:{port}/server/files/config/printer.cfg", timeout=4)
        if res.ok: return res.text
    except: pass
    return None


def _try_local_cfg():
    for path in _LOCAL_CFG_CANDIDATES:
        if os.path.isfile(path):
            with open(path, "r", errors="replace") as f: return f.read()
    return None


def _load_fallback_json():
    if os.path.isfile(_FALLBACK_JSON):
        with open(_FALLBACK_JSON) as f: return json.load(f)
    return {
        "printer_name": "Unknown Printer", "kinematics": "cartesian",
        "bed": {"size_x_mm":300,"size_y_mm":300,"size_z_mm":400,"origin_center":False},
        "motion": {"max_velocity_mm_s":300,"max_accel_mm_s2":3000,
                   "steps_per_mm_x":80,"steps_per_mm_y":80,"steps_per_mm_z":400,"steps_per_mm_e":415},
        "hotend": {"nozzle_diameter_mm":0.4,"filament_diameter_mm":1.75,"max_temp_c":300,
                   "pid_kp":21.0,"pid_ki":1.08,"pid_kd":100.0},
        "bed_heater": {"max_temp_c":120,"pid_kp":40.0,"pid_ki":4.0,"pid_kd":100.0},
        "print": {"layer_height_mm":0.2,"line_width_mm":0.4,
                  "linear_advance_k":0.04,"max_volumetric_flow_mm3_s":12.0},
        "moonraker": {"ip":"100.88.38.105","port":7125},
        "alerts": {"lag_magnitude_warn_mm":0.8,"stress_score_warn":0.5,
                   "ext_heat_cycles_warn":500,"bed_heat_cycles_warn":500,
                   "thermal_runaway_delta_c":15.0,"thermal_runaway_window_s":5.0},
    }


def _merge_bed_safety(cache: dict) -> None:
    """Overlay custom bed geometry / OrcaSlicer exclusion zones into *cache*."""
    try:
        from digital_twin.bed_safety import bed_safety
        if "bed" not in cache:
            cache["bed"] = {}
        cache["bed"].update(bed_safety.to_dict())
    except Exception as e:
        logging.warning(f"Could not merge bed_safety into profile: {e}")


def reload():
    global _cache
    from config.cfg_parser import build_profile, profile_summary

    # 0. Sim profile override
    sim_profile_path = os.environ.get("INDUS_SIM_PROFILE")
    if sim_profile_path and os.path.isfile(sim_profile_path):
        _cache = build_profile(sim_profile_path, _OVERRIDES_PATH)
        _cache["_source"] = f"sim profile ({os.path.basename(sim_profile_path)})"
        logging.info(f"✅ Profile loaded from: {_cache['_source']}")
        _merge_bed_safety(_cache)
        _refresh_module_attrs()
        return _cache

    mr_ip, mr_port = settings.MOONRAKER_HOST, settings.MOONRAKER_PORT
    cfg_text = _fetch_cfg_from_moonraker(mr_ip, mr_port)
    source   = "unknown"

    if cfg_text:
        source = f"Moonraker ({mr_ip}:{mr_port})"
    else:
        cfg_text = _try_local_cfg()
        if cfg_text: source = "local printer.cfg"

    if cfg_text:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg",
                                         delete=False, dir=_HERE) as tmp:
            tmp.write(cfg_text); tmp_path = tmp.name
        try:
            _cache = build_profile(tmp_path, _OVERRIDES_PATH)
        finally:
            os.unlink(tmp_path)
    else:
        source = "printer_profile.json (fallback)"
        _cache = _load_fallback_json()

    _cache["_source"] = source
    logging.info(f"✅ Profile loaded from: {source}")

    # Overlay custom bed geometry / OrcaSlicer exclusion zones if configured
    _merge_bed_safety(_cache)

    _refresh_module_attrs()
    return _cache


def _refresh_module_attrs():
    import sys
    m = sys.modules[__name__]
    m.profile      = _cache
    m.bed          = _cache.get("bed", {})
    m.motion       = _cache.get("motion", {})
    m.hotend       = _cache.get("hotend", {})
    m.bed_heater   = _cache.get("bed_heater", {})
    m.print_cfg    = _cache.get("print", {})
    m.alerts_cfg   = _cache.get("alerts", {})
    m.power_cfg    = _cache.get("power", {})
    m.timelapse_cfg = _cache.get("timelapse", {})
    m.moonraker_url = settings.moonraker_url


def get_profile():    return _cache
def get_bed():        return _cache.get("bed", {})
def get_motion():     return _cache.get("motion", {})
def get_hotend():     return _cache.get("hotend", {})
def get_bed_heater(): return _cache.get("bed_heater", {})
def get_print_cfg():  return _cache.get("print", {})
def get_alerts():     return _cache.get("alerts", {})
def get_power_cfg():  return _cache.get("power", {})
def get_timelapse_cfg(): return _cache.get("timelapse", {})
def get_moonraker_url():
    # config/settings.py (.env-backed) is the single source of truth for
    # the Moonraker address. This used to read a second, independent value
    # out of indus_overrides.cfg — see CLAUDE_CONTEXT.md for why that was
    # a live bug and not just duplication.
    return settings.moonraker_url


# Load on import
if not _cache:
    reload()
    _refresh_module_attrs()

# Module-level shortcuts
profile = _cache
bed = _cache.get("bed", {})
motion = _cache.get("motion", {})
hotend = _cache.get("hotend", {})
bed_heater = _cache.get("bed_heater", {})
print_cfg = _cache.get("print", {})
alerts_cfg = _cache.get("alerts", {})
power_cfg = _cache.get("power", {})
timelapse_cfg = _cache.get("timelapse", {})
moonraker_url = get_moonraker_url()

def get_edge_inspection_cfg(): return _cache.get("edge_inspection", {})

def update_edge_inspection_cfg(overrides: dict) -> dict:
    """Same targeted-line-replacement approach as update_timelapse_cfg —
    preserves comments in indus_overrides.cfg instead of rewriting the
    whole file with configparser."""
    allowed = {
        "edge_inspection_enabled":       lambda v: "true" if v else "false",
        "edge_inspection_threshold_pct": lambda v: str(max(0.0, min(100.0, float(v)))),
        "edge_inspection_cooldown_s":    lambda v: str(max(0.0, float(v))),
    }
    if not os.path.isfile(_OVERRIDES_PATH):
        raise FileNotFoundError(_OVERRIDES_PATH)

    to_set = {k: fmt(overrides[k]) for k, fmt in allowed.items() if k in overrides}
    if not to_set:
        return _cache

    with open(_OVERRIDES_PATH, "r") as f:
        lines = f.readlines()

    seen = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in to_set:
            lines[i] = f"{key} = {to_set[key]}\n"
            seen.add(key)

    missing = [k for k in to_set if k not in seen]
    if missing:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        for k in missing:
            lines.append(f"{k} = {to_set[k]}\n")

    with open(_OVERRIDES_PATH, "w") as f:
        f.writelines(lines)

    return reload()

def update_timelapse_cfg(overrides: dict) -> dict:
    """Patch timelapse_* keys in indus_overrides.cfg on disk and reload the
    in-memory profile so the change takes effect immediately (used by the
    Settings > Timelapse tab). Uses targeted line replacement rather than
    rewriting the whole file with configparser, since configparser would
    silently strip every comment in the file — and this file is meant to be
    hand-readable too."""
    allowed = {
        "timelapse_enabled":    lambda v: "true" if v else "false",
        "timelapse_mode":       lambda v: "layer" if str(v).strip().lower() == "layer" else "interval",
        "timelapse_interval_s": lambda v: str(max(1, int(float(v)))),
        "timelapse_fps":        lambda v: str(max(1, int(float(v)))),
    }
    if not os.path.isfile(_OVERRIDES_PATH):
        raise FileNotFoundError(_OVERRIDES_PATH)

    to_set = {k: fmt(overrides[k]) for k, fmt in allowed.items() if k in overrides}
    if not to_set:
        return _cache

    with open(_OVERRIDES_PATH, "r") as f:
        lines = f.readlines()

    seen = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in to_set:
            lines[i] = f"{key} = {to_set[key]}\n"
            seen.add(key)

    missing = [k for k in to_set if k not in seen]
    if missing:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        for k in missing:
            lines.append(f"{k} = {to_set[k]}\n")

    with open(_OVERRIDES_PATH, "w") as f:
        f.writelines(lines)

    return reload()
