"""
config/loader.py
-----------------
Loads the printer profile in priority order:
  1. INDUS_SIM_PROFILE env var (set by main.py --profile flag)
  2. Fetch printer.cfg live from Moonraker API
  3. Local printer.cfg (common Klipper paths)
  4. printer_profile.json fallback
"""

import os, json, tempfile, requests

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


def _load_overrides_ip():
    import configparser
    cfg = configparser.ConfigParser(); cfg.optionxform = str
    if os.path.isfile(_OVERRIDES_PATH): cfg.read(_OVERRIDES_PATH)
    sec = dict(cfg["indus3d"]) if "indus3d" in cfg else {}
    return sec.get("moonraker_ip", "100.88.38.105"), int(sec.get("moonraker_port", "7125"))


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


def reload():
    global _cache
    from config.cfg_parser import build_profile, profile_summary

    # 0. Sim profile override
    sim_profile_path = os.environ.get("INDUS_SIM_PROFILE")
    if sim_profile_path and os.path.isfile(sim_profile_path):
        _cache = build_profile(sim_profile_path, _OVERRIDES_PATH)
        _cache["_source"] = f"sim profile ({os.path.basename(sim_profile_path)})"
        print(f"✅ Profile loaded from: {_cache['_source']}")
        _refresh_module_attrs()
        return _cache

    mr_ip, mr_port = _load_overrides_ip()
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
    print(f"✅ Profile loaded from: {source}")
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
    mr = _cache.get("moonraker", {})
    m.moonraker_url = f"http://{mr.get('ip','localhost')}:{mr.get('port',7125)}"


def get_profile():    return _cache
def get_bed():        return _cache.get("bed", {})
def get_motion():     return _cache.get("motion", {})
def get_hotend():     return _cache.get("hotend", {})
def get_bed_heater(): return _cache.get("bed_heater", {})
def get_print_cfg():  return _cache.get("print", {})
def get_alerts():     return _cache.get("alerts", {})
def get_moonraker_url():
    mr = _cache.get("moonraker", {})
    return f"http://{mr.get('ip','localhost')}:{mr.get('port',7125)}"


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
moonraker_url = get_moonraker_url()
