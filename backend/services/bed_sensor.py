"""
services/bed_sensor.py
----------------------
Reads live telemetry from the ESP8266 Multi-Sensor Hub daemon (http://127.0.0.1:7127/telemetry).
Provides BME280 enclosure environment (temperature, relative humidity, barometric pressure)
and ADXL345 Y-carriage bed acceleration & instantaneous jerk metrics.
"""

import logging
import requests
import time

_CACHE_TTL = 0.10  # 10 Hz cache
_DEFAULT = {
    "connected": False,
    "chamber": {
        "temp_c": None,
        "humidity_pct": None,
        "pressure_hpa": None,
    },
    "bed_accel": {
        "x_mg": 0,
        "y_mg": 0,
        "z_mg": 0,
        "jerk_mg": 0,
    },
    "crash_detected": False,
    "uptime_sec": 0,
}

class BedSensorClient:
    def __init__(self, url="http://127.0.0.1:7127/telemetry"):
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
                    "chamber": data.get("chamber", _DEFAULT["chamber"]),
                    "bed_accel": data.get("bed_accel", _DEFAULT["bed_accel"]),
                    "crash_detected": bool(data.get("crash_detected", False)),
                    "uptime_sec": int(data.get("uptime_sec", 0)),
                }
            else:
                self._cached["connected"] = False
        except Exception:
            self._cached["connected"] = False

        self._last_read = now
        return self._cached

    def reset_crash(self) -> bool:
        """Sends reset command to ESP8266."""
        try:
            resp = self._session.post("http://127.0.0.1:7127/reset_crash", timeout=1.0)
            return resp.status_code == 200
        except Exception:
            return False

bed_sensor = BedSensorClient()
