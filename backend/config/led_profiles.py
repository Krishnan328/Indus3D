"""
config/led_profiles.py
------------------------
Per-printer LED profile: which discovered LED(s) to drive, a brightness
scale, what color to show for each printer state (idle/heating/printing/
paused/complete/error/homing/probing/alert), and whether "printing" should
be a flat color or a progress-based gradient. Keyed by printer id from
config/printers.py, since different printers in a multi-printer setup may
have different LED wiring entirely — a profile that makes sense for one is
meaningless for another.

Persisted to led_profiles.json alongside printers.json / indus_overrides.cfg.
"""

import json
import logging
import os
from typing import Optional

from services.led_controller import hex_to_rgb01  # reuse the same validator

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROFILES_PATH = os.path.join(_HERE, "led_profiles.json")

# "alert" is not tied to a print_stats state the way the others are — it's
# the flash color used for transient runaway/fault corrective actions (see
# core/alert_actions.py), deliberately separate from the steady "error"
# color so a flash reads as "something just happened" rather than blending
# into "the printer is currently halted".
STATES = ("idle", "heating", "printing", "paused", "complete", "error", "homing", "probing", "alert")

_DEFAULT_COLORS = {
    "idle":     "#001428",
    "heating":  "#502000",
    "printing": "#00a000",
    "paused":   "#a06000",
    "complete": "#00c040",
    "error":    "#c00000",
    "homing":   "#0060c0",
    "probing":  "#a000a0",
    "alert":    "#ff2000",
}


def _default_profile() -> dict:
    return {
        "enabled": False,
        "led_names": [],
        "brightness": 100,
        "printing_gradient": False,
        "colors": dict(_DEFAULT_COLORS),
    }


def _load_all() -> dict:
    if os.path.isfile(_PROFILES_PATH):
        try:
            with open(_PROFILES_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logging.info(f"🔴 led_profiles.json unreadable, resetting: {e}")
    return {}


def _save_all(data: dict) -> None:
    tmp = _PROFILES_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _PROFILES_PATH)


def _normalize_led_names(profile: dict) -> list:
    """Reads both the current 'led_names' list and the older single
    'led_name' key (profiles saved before multi-LED support), so an
    existing led_profiles.json on disk from before this change still loads
    correctly instead of silently losing its configured LED."""
    names = profile.get("led_names")
    if isinstance(names, list) and names:
        return [n for n in names if isinstance(n, str) and n]
    legacy = profile.get("led_name")
    return [legacy] if isinstance(legacy, str) and legacy else []


def get_profile(printer_id: str) -> dict:
    """Always returns a complete, valid profile — filling in any missing
    states/fields with defaults, so callers (including the telemetry loop)
    never have to null-check individual entries."""
    all_profiles = _load_all()
    profile = all_profiles.get(printer_id) or {}
    merged = _default_profile()
    merged["enabled"] = bool(profile.get("enabled", False))
    merged["led_names"] = _normalize_led_names(profile)
    try:
        merged["brightness"] = max(0, min(100, int(profile.get("brightness", 100))))
    except (TypeError, ValueError):
        merged["brightness"] = 100
    merged["printing_gradient"] = bool(profile.get("printing_gradient", False))
    merged["colors"] = {**_DEFAULT_COLORS, **(profile.get("colors") or {})}
    return merged


def save_profile(printer_id: str, enabled: bool, led_names, brightness, printing_gradient: bool, colors: dict) -> dict:
    if led_names is None:
        led_names = []
    if not isinstance(led_names, list) or not all(isinstance(n, str) for n in led_names):
        raise ValueError("led_names must be a list of strings")

    try:
        brightness = max(0, min(100, int(brightness)))
    except (TypeError, ValueError):
        raise ValueError("brightness must be a number between 0 and 100")

    clean_colors = {}
    for state in STATES:
        value = (colors or {}).get(state, _DEFAULT_COLORS[state])
        hex_to_rgb01(value)  # raises ValueError on bad input — validate before saving
        clean_colors[state] = value

    all_profiles = _load_all()
    all_profiles[printer_id] = {
        "enabled": bool(enabled),
        "led_names": led_names,
        "brightness": brightness,
        "printing_gradient": bool(printing_gradient),
        "colors": clean_colors,
    }
    _save_all(all_profiles)
    return get_profile(printer_id)
