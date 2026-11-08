"""
plugins/spoolman_sync.py  (F1)
--------------------------------
Reconciles filament use between Spoolman and the filament-sensor daemon.

Moonraker already reports each print's use to Spoolman, so this plugin does
NOT report usage again (that would double-count). Instead, after each print it
compares what Spoolman recorded (change in the active spool's remaining
weight) with what the sensor measured (change in its spool_used_g), and:

  report (default when enabled)  records the comparison;
  apply                          if the sensor measured MORE than Spoolman
                                 recorded (by >10 % and >2 g), tops the spool up
                                 with the difference via PUT /v1/spool/<id>/use.

INDUS3D_SPOOLMAN_RECONCILE=off|report|apply   (default off)
Works through Moonraker's [spoolman] proxy, same as the dashboard's spool picker.
Without the sensor there is nothing to compare against, so only Spoolman's
figure is recorded.

GET /api/v1/plugins/spoolman_sync
"""

import logging
import os
import time
from collections import deque

from plugins._common import delayed, http_json

PLUGIN_INFO = {
    "title": "Spoolman reconciliation",
    "description": "Compares Spoolman's recorded filament use with the sensor's measurement; optionally tops up the difference.",
}

TOLERANCE_PCT = 10.0
MIN_DIFF_G = 2.0
SETTLE_S = 10.0


def reconcile(spoolman_used_g, sensor_used_g):
    """Pure: verdict dict. Positive ``delta_g`` means the sensor saw more than Spoolman recorded."""
    out = {"spoolman_used_g": spoolman_used_g, "sensor_used_g": sensor_used_g, "delta_g": None,
           "delta_pct": None, "verdict": "no_sensor"}
    if sensor_used_g is None or spoolman_used_g is None:
        return out
    delta = sensor_used_g - spoolman_used_g
    base = max(sensor_used_g, spoolman_used_g, 1e-9)
    out["delta_g"], out["delta_pct"] = round(delta, 2), round(delta / base * 100, 1)
    out["verdict"] = "agree" if abs(delta) < MIN_DIFF_G or abs(delta / base * 100) <= TOLERANCE_PCT else (
        "sensor_higher" if delta > 0 else "sensor_lower")
    return out


class SpoolmanSync:
    def __init__(self, mode=None, proxy=None, active_spool=None, sensor_used=None):
        self.mode = (os.environ.get("INDUS3D_SPOOLMAN_RECONCILE", "off") if mode is None else mode).lower()
        self._proxy = proxy or self._moonraker_proxy
        self._active_spool = active_spool or self._moonraker_active_spool
        self._sensor_used = sensor_used or self._sensor_used_g
        self.start = None
        self.results = deque(maxlen=30)

    @property
    def enabled(self):
        return self.mode in ("report", "apply")

    # -- io ------------------------------------------------------------------
    @staticmethod
    def _moonraker_proxy(method, path, body=None):
        from config.settings import settings
        r = http_json(f"{settings.moonraker_url}/server/spoolman/proxy", timeout=5, method="POST",
                      body={"request_method": method, "path": path, **({"body": body} if body is not None else {})})
        return r.get("result", r)

    @staticmethod
    def _moonraker_active_spool():
        from config.settings import settings
        r = http_json(f"{settings.moonraker_url}/server/spoolman/spool_id", timeout=3)
        return (r.get("result") or {}).get("spool_id")

    @staticmethod
    def _sensor_used_g():
        try:
            from plugins.filament_sensor import bridge
            v = (bridge.summary().get("raw") or {}).get("spool_used_g")
            return float(v) if isinstance(v, (int, float)) else None
        except Exception:  # noqa: BLE001
            return None

    def _remaining(self, spool_id):
        return float(self._proxy("GET", f"/v1/spool/{spool_id}")["remaining_weight"])

    # -- print lifecycle -----------------------------------------------------
    def on_start(self):
        sid = self._active_spool()
        if sid is None:
            self.start = None
            return
        self.start = {"spool_id": sid, "remaining": self._remaining(sid), "sensor": self._sensor_used(), "t": time.time()}

    def finish(self, run):
        st, self.start = self.start, None
        if not st:
            return None
        end_remaining = self._remaining(st["spool_id"])
        spoolman_used = round(st["remaining"] - end_remaining, 2)
        sensor_end = self._sensor_used()
        sensor_used = None if (st["sensor"] is None or sensor_end is None) else round(sensor_end - st["sensor"], 2)
        res = {"run": run["id"], "filename": run.get("filename"), "spool_id": st["spool_id"], "applied_g": 0.0,
               **reconcile(spoolman_used, sensor_used), "mode": self.mode, "ts": time.time()}
        if self.mode == "apply" and res["verdict"] == "sensor_higher":
            self._proxy("PUT", f"/v1/spool/{st['spool_id']}/use", {"use_weight": res["delta_g"]})
            res["applied_g"] = res["delta_g"]
        self.results.appendleft(res)
        return res

    def tick(self, snap, ctx):
        pass

    def on_run_start(self, run):
        if self.enabled:
            delayed(0.1, self.on_start)

    def on_run_finish(self, run):
        if self.enabled:
            delayed(SETTLE_S, self._finish_logged, run)

    def _finish_logged(self, run):
        try:
            self.finish(run)
        except Exception as e:  # noqa: BLE001
            logging.info(f"spoolman_sync: {e}")

    def status(self):
        return {"mode": self.mode, "enabled": self.enabled, "tracking": self.start, "results": list(self.results)}


sync = SpoolmanSync()


def register_hooks(hooks) -> None:
    from plugins.run_recorder import recorder
    recorder.on_finish(sync.on_run_finish)
    hooks.on("tick", _start_watch, priority=71)


_was_printing = {"v": False}


def _start_watch(snap, ctx):
    printing = snap.get("print_state") == "printing"
    if printing and not _was_printing["v"]:
        sync.on_run_start(None)
    _was_printing["v"] = printing


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_spoolman_sync", __name__, url_prefix="/api/v1/plugins/spoolman_sync")

    @bp.route("", methods=["GET"])
    def sync_status():
        return jsonify(sync.status())

    app.register_blueprint(bp)
