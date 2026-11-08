"""
services/filament_sensor.py
----------------------------
Reads live metrics from the Indus3D Smart Filament Sensor daemon (http://127.0.0.1:7126/status).
Provides measured filament diameter, feed speed, volumetric flow, remaining spool weight,
and runout/clog status to the digital twin and quality controller.
"""

import logging
import requests
import time

_CACHE_TTL = 0.10  # 10 Hz cache to match digital twin tick rate
_DEFAULT = {
    "connected": False,
    "diameter_mm": 1.750,
    "raw_dia_angle": 0,
    "filament_present": False,
    "position_mm": 0.0,
    "velocity_mm_s": 0.0,
    "volumetric_flow_mm3_s": 0.0,
    "remaining_spool_weight_g": 1000.0,
    "material": "PLA",
    "auto_flow_percent": 100.0,
    "fault_flags": 0,
    "clog_detected": False,
    "runout_active": False,
}

class FilamentSensorClient:
    def __init__(self, url="http://127.0.0.1:7126/status"):
        self.url = url
        self._cached = dict(_DEFAULT)
        self._last_read = 0.0
        self._session = requests.Session()

    def read(self) -> dict:
        now = time.time()
        if now - self._last_read < _CACHE_TTL:
            return self._cached

        try:
            resp = self._session.get(self.url, timeout=0.08)
            if resp.status_code == 200:
                data = resp.json()
                self._cached = {
                    "connected": bool(data.get("connected", False)),
                    "diameter_mm": float(data.get("diameter_mm", 1.750)),
                    "raw_dia_angle": int(data.get("raw_dia_angle", 0)),
                    "filament_present": bool(data.get("filament_present", False)),
                    "position_mm": float(data.get("position_mm", 0.0)),
                    "velocity_mm_s": float(data.get("velocity_mm_s", 0.0)),
                    "volumetric_flow_mm3_s": float(data.get("volumetric_flow_mm3_s", 0.0)),
                    "remaining_spool_weight_g": float(data.get("remaining_spool_weight_g", 1000.0)),
                    "material": str(data.get("material", "PLA")),
                    "auto_flow_percent": float(data.get("auto_flow_percent", 100.0)),
                    "fault_flags": int(data.get("fault_flags", 0)),
                    "clog_detected": bool(data.get("clog_detected", False)),
                    "runout_active": bool(data.get("runout_active", False)),
                }
            else:
                self._cached["connected"] = False
        except Exception:
            self._cached["connected"] = False

        self._last_read = now
        return self._cached

filament_sensor = FilamentSensorClient()
