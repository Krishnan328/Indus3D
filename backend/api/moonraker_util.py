"""Shared helpers for backend routes that talk to Moonraker.

Phase-0 foundation for the typed control endpoints (macros, heaters, fans, ...):

* ``list_objects`` / ``macro_names``  what Klipper actually has, cached briefly
* ``valid_name``                      names from the browser are only ever accepted
                                      if they are in that list (never pasted into G-code)
* ``run_script``                      the one place a backend-built script is sent
* ``heater_limits``                   configured min/max temperatures, for bounds checks
* ``build_macro_script``              strict macro-call builder

Nothing here accepts raw G-code from a client.
"""

import re
import threading
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from config.settings import settings

OBJECT_TTL_S = 30.0
LIMITS_TTL_S = 60.0
TIMEOUT_S = 5

_MACRO_PARAM_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
_MACRO_PARAM_VAL = re.compile(r"^[A-Za-z0-9_.+\-:/]{0,64}$")
_MACRO_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, object]] = {}


class MoonrakerError(RuntimeError):
    """Moonraker unreachable or it refused the request."""


def url(path: str) -> str:
    return f"{settings.moonraker_url}{path}"


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def _cached(key: str, ttl: float, fetch):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fetch()                                    # outside the lock: a slow Moonraker must not block readers
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def get_json(path: str, timeout: float = TIMEOUT_S) -> dict:
    try:
        res = requests.get(url(path), timeout=timeout)
    except requests.RequestException as e:
        raise MoonrakerError(f"Moonraker unreachable: {e}") from e
    if not res.ok:
        raise MoonrakerError(f"Moonraker answered {res.status_code} for {path.split('?')[0]}")
    try:
        return res.json().get("result", {})
    except ValueError as e:
        raise MoonrakerError("Moonraker sent invalid JSON") from e


def list_objects() -> List[str]:
    """Names of all Klipper objects, e.g. 'extruder', 'gcode_macro PAUSE', 'output_pin beeper'."""
    return _cached("objects", OBJECT_TTL_S, lambda: list(get_json("/printer/objects/list").get("objects", [])))


def macro_names() -> List[str]:
    return sorted(o.split(" ", 1)[1] for o in list_objects() if o.startswith("gcode_macro "))


def valid_name(prefix: str, name: str) -> Optional[str]:
    """The canonical object name for ``name`` (case-insensitive) within the family ``prefix``
    ('gcode_macro', 'output_pin', 'fan_generic', ...), or None if Klipper has no such object."""
    if not isinstance(name, str) or not name or len(name) > 64:
        return None
    want = f"{prefix} {name}".lower()
    for obj in list_objects():
        if obj.lower() == want:
            return obj.split(" ", 1)[1]
    return None


def build_macro_script(name: str, params: Optional[dict]) -> str:
    """``NAME KEY=value ...`` with every part validated. Raises ValueError on anything odd."""
    if not _MACRO_NAME.match(name or ""):
        raise ValueError("invalid macro name")
    parts = [name]
    for key, value in (params or {}).items():
        if not _MACRO_PARAM_KEY.match(str(key)):
            raise ValueError(f"invalid parameter name: {key!r}")
        text = str(value)
        if isinstance(value, bool):
            text = "1" if value else "0"
        if not _MACRO_PARAM_VAL.match(text):
            raise ValueError(f"invalid value for {key}")
        parts.append(f"{str(key).upper()}={text}")
    return " ".join(parts)


def run_script(script: str, timeout: float = 10) -> requests.Response:
    """POST a backend-built script to Moonraker. The caller is responsible for having validated it."""
    try:
        return requests.post(url("/printer/gcode/script"), params={"script": script}, timeout=timeout)
    except requests.RequestException as e:
        raise MoonrakerError(f"Moonraker unreachable: {e}") from e


def query_objects(names: List[str]) -> dict:
    """``{object: {field: value}}`` for the given object names (spaces are URL-encoded)."""
    if not names:
        return {}
    qs = "&".join(quote(n, safe="") for n in names)
    return get_json(f"/printer/objects/query?{qs}").get("status", {})


def heater_limits() -> Dict[str, Dict[str, float]]:
    """``{heater: {"min_temp", "max_temp"}}`` from the Klipper configuration."""
    def fetch():
        settings_ = get_json("/printer/objects/query?configfile=settings").get("status", {}) \
            .get("configfile", {}).get("settings", {})
        out = {}
        for section, cfg in settings_.items():
            if (section == "extruder" or re.match(r"^extruder\d+$", section) or section == "heater_bed"
                    or section.startswith("heater_generic ")) and isinstance(cfg, dict):
                lo, hi = cfg.get("min_temp"), cfg.get("max_temp")
                if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                    out[section] = {"min_temp": float(lo), "max_temp": float(hi)}
        return out
    return _cached("limits", LIMITS_TTL_S, fetch)
