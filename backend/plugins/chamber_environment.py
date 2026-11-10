"""
plugins/chamber_environment.py  (C4)
--------------------------------------
Advice from chamber climate (needs the esp_bed_hub plugin and its BME280):

* high humidity   chamber RH >= INDUS3D_HUMIDITY_WARN_PCT (default 60) for
                  10 minutes -> "filament may absorb moisture / dry before use".
                  This is the humidity of the chamber AIR, not of the spool.
* heat creep      chamber temperature above a material limit (PLA 40, PETG 55,
                  TPU 45 °C; others unchecked) -> risk of softening in the
                  heatbreak / extruder gear jams. Material comes from the
                  active virtual spool.

Warn-only: it notifies once per condition (re-arms after the condition has
cleared for 5 minutes) and never touches the controller or the printer.

GET /api/v1/plugins/chamber_environment
"""

import os
import time
from collections import deque

from plugins._common import active_material, notify_safe

PLUGIN_INFO = {
    "title": "Chamber environment",
    "description": "Warns about humid chamber air and over-hot chambers for the loaded material (needs the ESP hub).",
}

HOLD_S = 600.0
CLEAR_S = 300.0
TEMP_LIMIT_C = {"PLA": 40.0, "PETG": 55.0, "TPU": 45.0}


class ChamberEnv:
    def __init__(self, source=None, material=None, notify=notify_safe, humidity_limit=None):
        self._source = source or self._hub_source
        self._material = material or active_material
        self.notify = notify
        self.humidity_limit = float(os.environ.get("INDUS3D_HUMIDITY_WARN_PCT", 60)) \
            if humidity_limit is None else humidity_limit
        self.since, self.clear_since, self.raised = {}, {}, {}
        self.events = deque(maxlen=50)
        self.last = None
        self._mat_cache = (float("-inf"), "unknown")

    @staticmethod
    def _hub_source():
        from plugins.esp_bed_hub import hub
        return hub.chamber()

    def _mat(self, now):
        if now - self._mat_cache[0] > 60:
            self._mat_cache = (now, str(self._material()).upper())
        return self._mat_cache[1]

    def _cond(self, kind, holds, now, msg):
        if holds:
            self.clear_since.pop(kind, None)
            start = self.since.setdefault(kind, now)
            if now - start >= HOLD_S and kind not in self.raised:
                self.raised[kind] = now
                self.events.appendleft({"ts": now, "kind": kind, "detail": msg})
                self.notify(f"🌡️ Indus3D chamber: {msg}")
        else:
            self.since.pop(kind, None)
            if kind in self.raised:
                start = self.clear_since.setdefault(kind, now)
                if now - start >= CLEAR_S:
                    self.raised.pop(kind, None)
                    self.clear_since.pop(kind, None)

    def tick(self, snap, ctx):
        now = ctx.get("now", time.time())
        c = self._source()
        self.last = c
        if not c:
            return
        rh, temp = c.get("humidity_pct"), c.get("temp_c")
        if rh is not None:
            self._cond("high_humidity", rh >= self.humidity_limit, now,
                       f"chamber air at {rh:.0f}% RH (limit {self.humidity_limit:.0f}%) — consider drying the filament")
        mat = self._mat(now)
        limit = TEMP_LIMIT_C.get(mat)
        if temp is not None and limit is not None:
            self._cond("heat_creep", temp > limit, now,
                       f"chamber at {temp:.0f} °C is above the {limit:.0f} °C limit for {mat} (heat creep risk)")

    def status(self):
        return {"humidity_limit_pct": self.humidity_limit, "material": self._mat_cache[1],
                "latest": self.last, "raised": sorted(self.raised), "events": list(self.events),
                "note": "Humidity is chamber air, not spool moisture."}


env = ChamberEnv()


def register_hooks(hooks) -> None:
    hooks.on("tick", env.tick, priority=47)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_chamber_environment", __name__, url_prefix="/api/v1/plugins/chamber_environment")

    @bp.route("", methods=["GET"])
    def env_status():
        return jsonify(env.status())

    app.register_blueprint(bp)
