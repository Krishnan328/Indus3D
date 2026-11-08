"""
plugins/esp_bed_hub.py  (C3)
------------------------------
Brings the ESP8266 bed hub (helpers/filament_sensor/esp8266_sensor_hub) into
Indus3D: bed accelerometer/jerk, the BME280 chamber readings and its crash
latch. Polls the hub's GET /telemetry every 2 s in a background thread.
Disabled unless INDUS3D_ESP_HUB_URL is set (e.g. http://192.168.1.50).

* A crash latch rising edge raises a notification and an event. The hub already
  pauses the print itself through Moonraker; this plugin only reports it.
* chamber_environment reads this plugin's latest chamber values.

GET /api/v1/plugins/esp_bed_hub
"""

import logging
import os
import time
from collections import deque

from plugins._common import Poller, http_json, notify_safe

PLUGIN_INFO = {
    "title": "ESP8266 bed hub",
    "description": "Bed acceleration, chamber climate and crash latch from the ESP8266 hub. Opt-in via INDUS3D_ESP_HUB_URL.",
}


class EspHub:
    def __init__(self, url=None, fetch=None, notify=notify_safe):
        self.url = os.environ.get("INDUS3D_ESP_HUB_URL", "") if url is None else url
        self._fetch = fetch or (lambda u: http_json(u.rstrip("/") + "/telemetry", timeout=1.5))
        self.notify = notify
        self.data = None
        self.connected = False
        self.last_ok = None
        self.last_error = None
        self.crash_latched = False
        self.events = deque(maxlen=50)
        self._poller = Poller(self.poll_once, 2.0, "esp-bed-hub")

    @property
    def enabled(self):
        return bool(self.url)

    def poll_once(self, now=None):
        now = now or time.time()
        try:
            d = self._fetch(self.url)
        except Exception as e:  # noqa: BLE001
            if self.connected:
                logging.info(f"ESP bed hub unreachable: {e}")
            self.connected, self.last_error = False, f"{type(e).__name__}: {e}"
            return None
        self.data, self.connected, self.last_ok, self.last_error = d, True, now, None
        crash = bool(d.get("crash_detected"))
        if crash and not self.crash_latched:
            info = d.get("crash_info") or {}
            self.events.appendleft({"ts": now, "kind": "crash", "peak_jerk_mg": info.get("peak_jerk_mg")})
            self.notify(f"💥 Indus3D bed hub: crash detected (peak jerk {info.get('peak_jerk_mg', '?')} mg)")
        self.crash_latched = crash
        return d

    def chamber(self, max_age_s=10.0, now=None):
        """{"temp_c","humidity_pct","pressure_hpa"} when fresh and valid, else None."""
        now = now or time.time()
        if not (self.connected and self.last_ok and now - self.last_ok <= max_age_s and self.data):
            return None
        c = self.data.get("chamber") or {}
        return c if c.get("temp_c") is not None else None

    def tick(self, snap, ctx):
        if self.enabled:
            self._poller.start()

    def status(self):
        d = self.data or {}
        return {"enabled": self.enabled, "url": self.url or None, "connected": self.connected,
                "last_ok": self.last_ok, "last_error": self.last_error, "crash_latched": self.crash_latched,
                "bed_accel": d.get("bed_accel"), "chamber": d.get("chamber"), "events": list(self.events)}


hub = EspHub()


def register_hooks(hooks) -> None:
    hooks.on("tick", hub.tick, priority=46)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_esp_bed_hub", __name__, url_prefix="/api/v1/plugins/esp_bed_hub")

    @bp.route("", methods=["GET"])
    def hub_status():
        return jsonify(hub.status())

    app.register_blueprint(bp)
