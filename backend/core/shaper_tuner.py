"""Guided Klipper input-shaper calibration.

Klipper owns the accelerometer analysis. This module starts its
``SHAPER_CALIBRATE`` command, reads the textual recommendation from
Moonraker's console history, and can persist the approved Y-axis baseline
without rewriting comments in ``indus_overrides.cfg``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
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


def _find_latest_resonance_csv(axis: str) -> str | None:
    """Return the most recent Klipper resonance CSV for the given axis, or None.

    Klipper saves files like ``/tmp/resonances_x_*.csv`` or in
    ``~/printer_data/config/`` depending on version. We search both locations
    and return the newest match.
    """
    candidates = []
    search_dirs = [
        "/tmp",
        os.path.expanduser("~/printer_data/config"),
        os.path.expanduser("~/klipper_config"),
    ]
    pattern = re.compile(rf"resonances_{re.escape(axis)}_.*\.csv$", re.IGNORECASE)
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if pattern.match(fname):
                candidates.append(os.path.join(d, fname))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


_BIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "dsp", "target", "release", "indus3d-dsp"
)


def analyse_csv_with_rust(csv_path: str, axis: str = "xyz") -> dict | None:
    """Run the Rust resonance analyser on a Klipper TEST_RESONANCES CSV file.

    Returns the parsed ShaperRecommendation dict from Rust, or None if the
    binary is not available or the analysis fails. The caller should fall back
    to the Moonraker G-code store polling path when this returns None.

    Expected Rust JSON output::

        {
            "shaper_type": "mzv",
            "freq_hz": 45.6,
            "damping_ratio": 0.08,
            "peak_reduction_db": 25.0
        }
    """
    bin_path = os.path.abspath(_BIN_PATH)
    if not os.path.isfile(bin_path):
        return None
    try:
        result = subprocess.run(
            [bin_path, "--analyze-csv", csv_path, "--axis", axis],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logging.warning("indus3d-dsp analyser non-zero exit: %s", result.stderr.strip())
            return None
        return json.loads(result.stdout.strip())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logging.warning("Rust resonance analyser failed: %s", exc)
        return None


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
        csv_tried = False
        while time.time() < deadline:
            time.sleep(_POLL_INTERVAL_S)

            # ── Fast path: check if Klipper wrote a CSV that the Rust
            # analyser can process directly (avoids parsing G-code text)
            if not csv_tried:
                csv_path = _find_latest_resonance_csv(self.axis)
                if csv_path:
                    csv_tried = True
                    rust_result = analyse_csv_with_rust(csv_path, self.axis)
                    freq_val = rust_result.get("shaper_freq") or rust_result.get("freq_hz") or rust_result.get("peak_hz")
                    if rust_result and freq_val and float(freq_val) > 0:
                        self.result = {
                            "shaper_type": rust_result.get("shaper_type", "mzv"),
                            "freq":        float(freq_val),
                            "damping_ratio": rust_result.get("damping_ratio"),
                            "peak_reduction_db": rust_result.get("reduction_db") or rust_result.get("peak_reduction_db"),
                        }
                        self.status = "done"
                        return

            # ── Slow path: poll Moonraker G-code store for the text recommendation
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
