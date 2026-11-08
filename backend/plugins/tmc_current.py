"""
plugins/tmc_current.py  (C5)
------------------------------
Supplies the measured extruder current the clog detector has been missing.
The detector compares the current predicted from melt backpressure with
``ext["tmc_extruder_current_a"]``; nothing set that key, so it never fired.

Klipper does not report amps, but a TMC2209/2208 reports DRV_STATUS.cs_actual,
the driver's actual current scale (0-31). In stealthChop with its current
regulation, cs_actual rises with load, so the plugin estimates

    I ≈ run_current × (cs_actual + 1) / 32

and injects it into the controller's inputs while the reading is fresh (<3 s).

OPT-IN, because it changes behaviour: set INDUS3D_TMC_CURRENT=1. A wrong
estimate means false clog pauses, since a CLOG verdict pauses the print when the
auto-pilot is on. Before trusting it, run with the auto-pilot OFF and watch
shadow_mode / the tracker for "would pause" events during healthy prints; the
estimate is only meaningful with stealthChop and an extruder driver that
reports cs_actual (in spreadCycle cs_actual is constant).

INDUS3D_TMC_OBJECT   Klipper object name, default "tmc2209 extruder"

GET /api/v1/plugins/tmc_current
"""

import logging
import os
import time

from plugins._common import Poller, http_json

PLUGIN_INFO = {
    "title": "TMC extruder current",
    "description": "Estimates extruder current from the TMC driver so the clog detector can work. Opt-in.",
}

FRESH_S = 3.0


def estimate_current(run_current_a, cs_actual):
    if run_current_a is None or cs_actual is None:
        return None
    cs = max(0, min(31, int(cs_actual)))
    return round(float(run_current_a) * (cs + 1) / 32.0, 3)


class TmcCurrent:
    def __init__(self, enabled=None, obj=None, fetch=None):
        self.enabled = (os.environ.get("INDUS3D_TMC_CURRENT", "0") == "1") if enabled is None else enabled
        self.obj = os.environ.get("INDUS3D_TMC_OBJECT", "tmc2209 extruder") if obj is None else obj
        self._fetch = fetch or self._moonraker
        self.estimate = None
        self.cs_actual = None
        self.run_current = None
        self.updated = None
        self.last_error = None
        self._poller = Poller(self.poll_once, 0.5, "tmc-current")

    def _moonraker(self, obj):
        from urllib.parse import quote
        from config.settings import settings
        r = http_json(f"{settings.moonraker_url}/printer/objects/query?{quote(obj)}", timeout=1.0)
        return (r.get("result", {}).get("status", {}) or {}).get(obj)

    def poll_once(self, now=None):
        now = now or time.time()
        try:
            st = self._fetch(self.obj)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            return None
        drv = (st or {}).get("drv_status") or {}
        self.run_current = (st or {}).get("run_current")
        self.cs_actual = drv.get("cs_actual")
        est = estimate_current(self.run_current, self.cs_actual)
        if est is None:
            self.last_error = f"object '{self.obj}' has no drv_status.cs_actual/run_current (wrong name, or driver not reporting)"
            return None
        self.estimate, self.updated, self.last_error = est, now, None
        return est

    def inputs(self, snap, kin, thm, ext, ctx):
        if not self.enabled:
            return
        now = ctx.get("now", time.time())
        if self.estimate is not None and self.updated and now - self.updated <= FRESH_S:
            ext["tmc_extruder_current_a"] = self.estimate

    def tick(self, snap, ctx):
        if self.enabled:
            self._poller.start()

    def status(self):
        return {"enabled": self.enabled, "object": self.obj, "cs_actual": self.cs_actual,
                "run_current_a": self.run_current, "estimated_current_a": self.estimate,
                "updated": self.updated, "last_error": self.last_error,
                "warning": "Estimate from cs_actual; validate against shadow-mode 'would pause' events before enabling "
                           "the auto-pilot with this on." if self.enabled else "Disabled (set INDUS3D_TMC_CURRENT=1)."}


tmc = TmcCurrent()


def register_hooks(hooks) -> None:
    hooks.on("controller.inputs", tmc.inputs, priority=50)
    hooks.on("tick", tmc.tick, priority=48)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_tmc_current", __name__, url_prefix="/api/v1/plugins/tmc_current")

    @bp.route("", methods=["GET"])
    def tmc_status():
        return jsonify(tmc.status())

    app.register_blueprint(bp)
