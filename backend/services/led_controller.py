"""
services/led_controller.py
---------------------------
Discovers Klipper-configured LED hardware ([neopixel], [led], [dotstar],
[pca9533], [pca9632] config sections) via Moonraker's object list, and sends
SET_LED commands to control them.

Colors are handled as "#rrggbb" hex strings everywhere outside this module
(API, config storage, frontend) — Klipper's SET_LED wants 0.0-1.0 floats per
channel, so the hex<->float conversion happens only here, at the boundary.
"""

import colorsys
import logging
import re
import threading
import time

import requests

from config.settings import settings

# Klipper config-section prefixes that represent controllable LED hardware.
# Each config entry looks like "neopixel my_leds" in Moonraker's object list.
_LED_PREFIXES = ("neopixel ", "led ", "dotstar ", "pca9533 ", "pca9632 ")

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _mr(path: str) -> str:
    return f"{settings.moonraker_url}{path}"


def hex_to_rgb01(hex_color: str):
    """'#rrggbb' -> (r, g, b) floats in 0.0-1.0, for SET_LED's RED/GREEN/BLUE args."""
    m = _HEX_RE.match((hex_color or "").strip())
    if not m:
        raise ValueError(f"Invalid color {hex_color!r} — expected #rrggbb")
    v = m.group(1)
    r = int(v[0:2], 16) / 255.0
    g = int(v[2:4], 16) / 255.0
    b = int(v[4:6], 16) / 255.0
    return r, g, b


def discover_leds() -> list:
    """Ask Moonraker which LED-capable objects are configured. Returns
    [{"name": "my_leds", "type": "neopixel"}, ...] — empty list (not an
    exception) if Moonraker is unreachable, since this is called both from
    an interactive settings tab (fine to show 'none found') and from the
    telemetry loop (must never raise there)."""
    try:
        res = requests.get(_mr("/printer/objects/list"), timeout=3)
        if not res.ok:
            return []
        objects = res.json().get("result", {}).get("objects", [])
    except Exception as e:
        logging.info(f"🔴 LED discovery failed: {e}")
        return []

    found = []
    for obj in objects:
        for prefix in _LED_PREFIXES:
            if obj.startswith(prefix):
                found.append({"name": obj[len(prefix):], "type": prefix.strip()})
                break
    return found


def set_led(name: str, hex_color: str) -> bool:
    """Send SET_LED for one Klipper-configured LED object. Returns False
    (logs, doesn't raise) on any failure — callers on the telemetry thread
    must never be blocked or crashed by an LED write failing."""
    try:
        r, g, b = hex_to_rgb01(hex_color)
    except ValueError as e:
        logging.info(f"🔴 set_led: {e}")
        return False
    gcode = f"SET_LED LED={name} RED={r:.3f} GREEN={g:.3f} BLUE={b:.3f}"
    try:
        res = requests.post(_mr("/printer/gcode/script"), params={"script": gcode}, timeout=3)
        return res.ok
    except Exception as e:
        logging.info(f"🔴 set_led({name}) failed: {e}")
        return False


def set_leds(names: list, hex_color: str) -> bool:
    """Apply one color to several LED objects (a profile can drive more
    than one strip/ring at once). Returns True only if every LED accepted
    the command — callers that only care "did anything happen" should treat
    a partial failure as a failure worth surfacing, not silently ignore it."""
    if not names:
        return False
    return all(set_led(name, hex_color) for name in names)


def scale_hex(hex_color: str, brightness_pct) -> str:
    """Scale a '#rrggbb' color by a 0-100 brightness percentage, returning
    a new hex string. Used so the whole profile can be dimmed with one
    slider instead of re-picking every state color."""
    try:
        pct = max(0, min(100, float(brightness_pct))) / 100.0
    except (TypeError, ValueError):
        pct = 1.0
    r, g, b = hex_to_rgb01(hex_color)
    return "#{:02x}{:02x}{:02x}".format(
        round(r * pct * 255), round(g * pct * 255), round(b * pct * 255)
    )


def progress_gradient_color(percent: float) -> str:
    """Maps 0-100 print progress to a hue sweep from blue (0%) through
    green/yellow to red (100%) — the same 'jet'-style gradient used by the
    G-code viewer's color-by-height mode, for visual consistency across the
    app. Used by the optional 'Progress Gradient' printing-state mode."""
    pct = max(0, min(100, percent)) / 100.0
    hue = 0.66 * (1 - pct)  # 0.66 (blue) -> 0.0 (red)
    r, g, b = colorsys.hls_to_rgb(hue, 0.5, 1.0)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def flash(names: list, flash_hex: str, restore_hex: str = None, times: int = 4, interval: float = 0.25):
    """Briefly alternate an LED between flash_hex and off (or restore_hex,
    if given) a few times, then leave it on restore_hex — used for
    transient alert conditions, so they're visually distinct from a steady
    status color even when both would otherwise be 'red'. Runs in a
    background thread: this is called from the telemetry tick (via
    core/alert_actions.py), which must never block on a ~1s flash
    sequence."""
    if not names:
        return

    def _run():
        off = restore_hex or "#000000"
        for _ in range(max(1, times)):
            set_leds(names, flash_hex)
            time.sleep(interval / 2)
            set_leds(names, off)
            time.sleep(interval / 2)
        if restore_hex:
            set_leds(names, restore_hex)

    threading.Thread(target=_run, daemon=True).start()
