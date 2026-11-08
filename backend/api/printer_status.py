"""Klipper object status for the UI (heaters, sensors, fans, outputs, leveling helpers).

One shared, cached query: however many browsers poll, Moonraker is asked at most once per
``TTL_S``, and this runs on the request thread, never on the digital-twin tick (which keeps its own
small object set). The result also says what the printer *can* do (capabilities), so the UI only
offers controls for hardware Klipper actually has.
"""

import re
import threading
import time
from typing import Dict, List

from api import moonraker_util as mu

TTL_S = 1.0

# Klipper object families worth showing, as (prefix-or-exact name).
_HEATER = re.compile(r"^(extruder\d*|heater_bed|heater_generic .+)$")
_SENSOR = re.compile(r"^(temperature_sensor|temperature_fan) .+$")
_FAN = re.compile(r"^(fan|(heater_fan|controller_fan|fan_generic) .+)$")
_OUTPUT = re.compile(r"^output_pin .+$")
_FILAMENT = re.compile(r"^filament_(switch|motion)_sensor .+$")
_SINGLE = ("probe", "bltouch", "z_tilt", "quad_gantry_level", "screws_tilt_adjust", "bed_screws", "manual_probe",
           "firmware_retraction", "idle_timeout", "gcode_move", "exclude_object", "pause_resume", "input_shaper",
           "bed_mesh", "z_thermal_adjust")

_lock = threading.Lock()
_snap = {"t": 0.0, "value": None}


def classify(objects: List[str]) -> Dict[str, List[str]]:
    """Group Klipper object names; keeps only the families the UI knows."""
    groups = {"heaters": [], "sensors": [], "fans": [], "outputs": [], "filament_sensors": [], "singles": []}
    for o in objects:
        if _HEATER.match(o):
            groups["heaters"].append(o)
        elif _SENSOR.match(o):
            groups["sensors"].append(o)
        elif _FAN.match(o):
            groups["fans"].append(o)
        elif _OUTPUT.match(o):
            groups["outputs"].append(o)
        elif _FILAMENT.match(o):
            groups["filament_sensors"].append(o)
        elif o in _SINGLE:
            groups["singles"].append(o)
    return groups


def capabilities(objects: List[str], groups: Dict[str, List[str]]) -> dict:
    has = set(objects)
    macros = sorted(o.split(" ", 1)[1] for o in objects if o.startswith("gcode_macro "))
    lower = {m.upper() for m in macros}

    def first(*names):
        return next((n for n in names if n in lower), None)
    return {
        "macros": macros,
        "heaters": groups["heaters"], "temperature_sensors": [s for s in groups["sensors"]],
        "fans": groups["fans"], "outputs": groups["outputs"], "filament_sensors": groups["filament_sensors"],
        "extruders": [h for h in groups["heaters"] if h.startswith("extruder")],
        "probe": bool({"probe", "bltouch"} & has),
        "z_tilt": "z_tilt" in has, "quad_gantry_level": "quad_gantry_level" in has,
        "screws_tilt_adjust": "screws_tilt_adjust" in has, "bed_screws": "bed_screws" in has,
        "firmware_retraction": "firmware_retraction" in has, "exclude_object": "exclude_object" in has,
        "bed_mesh": "bed_mesh" in has,
        # Fluidd-style tool-card macros: first matching name wins (case-insensitive)
        "tool_macros": {
            "load_filament": first("LOAD_FILAMENT", "FILAMENT_LOAD", "M701"),
            "unload_filament": first("UNLOAD_FILAMENT", "FILAMENT_UNLOAD", "M702"),
            "clean_nozzle": first("CLEAN_NOZZLE", "NOZZLE_CLEAN", "WIPE_NOZZLE", "NOZZLE_WIPE", "G12"),
            "park_toolhead": first("PARK_TOOLHEAD", "TOOLHEAD_PARK", "G27"),
        },
    }


def _fetch() -> dict:
    objects = mu.list_objects()
    groups = classify(objects)
    names = [n for key in ("heaters", "sensors", "fans", "outputs", "filament_sensors", "singles") for n in groups[key]]
    return {
        "ok": True, "ts": time.time(),
        "status": mu.query_objects(names),
        "capabilities": capabilities(objects, groups),
        "limits": _safe_limits(),
    }


def _safe_limits() -> dict:
    try:
        return mu.heater_limits()
    except mu.MoonrakerError:
        return {}


def snapshot(now: float = None) -> dict:
    """Cached status; raises ``MoonrakerError`` if Moonraker cannot be reached."""
    now = time.monotonic() if now is None else now
    with _lock:
        if _snap["value"] is not None and now - _snap["t"] < TTL_S:
            return _snap["value"]
    value = _fetch()
    with _lock:
        _snap["t"], _snap["value"] = time.monotonic(), value
    return value


def reset() -> None:
    with _lock:
        _snap["t"], _snap["value"] = 0.0, None
