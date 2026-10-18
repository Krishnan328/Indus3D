"""Guided Klipper input-shaper calibration.

Klipper owns the accelerometer analysis. This module starts its
``SHAPER_CALIBRATE`` command, reads the textual recommendation from
Moonraker's console history, and can persist the approved Y-axis baseline
without rewriting comments in ``indus_overrides.cfg``.
"""

import os
import re
import threading
import time

from digital_twin.quality_controller import quality_controller
from services.moonraker_client import MoonrakerClient

_client = MoonrakerClient()
_TIMEOUT_S = 150
_POLL_INTERVAL_S = 3
_CFG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "indus_overrides.cfg")


def _patterns_for_axis(axis: str):
    return [
        re.compile(
            rf"Recommended shaper_type_{axis}\s*=\s*(\w+),\s*shaper_freq_{axis}\s*=\s*([\d.]+)\s*Hz",
            re.IGNORECASE,
        ),
        re.compile(r"Recommended shaper is\s+(\w+)\s*@\s*([\d.]+)\s*Hz", re.IGNORECASE),
    ]


class ShaperCalibrationJob:
    def __init__(self):
        self.status = "idle"
        self.axis = None
        self.result = None
        self.error = None

    def start(self, axis: str = "y") -> dict:
        if self.status == "running":
            return {"status": "already_running"}
        self.status, self.axis = "running", axis.lower()
        self.result = self.error = None
        threading.Thread(target=self._run, daemon=True).start()
        return {"status": "started", "axis": self.axis}

    def _run(self):
        trigger_time = time.time()
        if not _client.send_gcode(f"SHAPER_CALIBRATE AXIS={self.axis.upper()}"):
            self.status = "error"
            self.error = "Failed to send SHAPER_CALIBRATE — check the Moonraker connection"
            return

        deadline = trigger_time + _TIMEOUT_S
        patterns = _patterns_for_axis(self.axis)
        while time.time() < deadline:
            time.sleep(_POLL_INTERVAL_S)
            for message in _client.get_gcode_store(count=200):
                if message.get("time", 0) < trigger_time:
                    continue
                for pattern in patterns:
                    match = pattern.search(message.get("message", ""))
                    if match:
                        self.result = {"shaper_type": match.group(1).lower(), "freq": float(match.group(2))}
                        self.status = "done"
                        return
        self.status = "timeout"
        self.error = f"No recommendation appeared within {_TIMEOUT_S}s — check the Klipper console"

    def status_dict(self) -> dict:
        return {"status": self.status, "axis": self.axis, "result": self.result, "error": self.error}


current_job = ShaperCalibrationJob()


def _set_cfg_value(key: str, value: str) -> bool:
    """Replace one value while preserving the hand-written config comments."""
    try:
        with open(_CFG_PATH, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return False

    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*).*$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            lines[index] = f"{match.group(1)}{value}\n"
            break
    else:
        for index, line in enumerate(lines):
            if line.strip() == "[indus3d]":
                lines.insert(index + 1, f"{key} = {value}\n")
                break
        else:
            return False

    with open(_CFG_PATH, "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    return True


def apply_result(shaper_type: str, freq: float) -> dict:
    if freq <= 0 or not re.fullmatch(r"[A-Za-z0-9_]+", shaper_type or ""):
        return {"applied": False, "error": "Invalid shaper recommendation"}
    type_saved = _set_cfg_value("y_shaper_type", shaper_type.lower())
    freq_saved = _set_cfg_value("y_resonance_hz", f"{freq:.1f}")
    if type_saved and freq_saved:
        quality_controller.reload_shaper_baseline()
    return {"applied": type_saved and freq_saved}


def set_bed_mass(grams: float) -> dict:
    if grams <= 0:
        return {"applied": False, "error": "Bed mass must be greater than zero"}
    saved = _set_cfg_value("bed_mass_g", f"{grams:.1f}")
    if saved:
        quality_controller.reload_shaper_baseline()
    return {"applied": saved}
