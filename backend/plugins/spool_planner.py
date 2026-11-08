"""
plugins/spool_planner.py  (C2)
--------------------------------
"Will this spool finish this print?" Compares the filament a G-code file needs
(slicer figures in Moonraker's file metadata) with what is left on the spool,
with a 5 % + 5 g safety margin. Remaining filament comes from, in order:

  1. the filament-sensor daemon (spool_remaining_g) when it is connected,
  2. the virtual spool (virtual_spool_weight_g − virtual_spool_used_g).

A print that starts without enough filament raises a notification; the same
check is available before printing via the endpoint.

GET /api/v1/plugins/spool_planner?filename=<gcode file>
"""

import math
import time
from collections import deque

from plugins._common import http_json, notify_safe

PLUGIN_INFO = {
    "title": "Spool runout planner",
    "description": "Checks whether the remaining spool covers the print, before and at print start.",
}

MARGIN_FRACTION, MARGIN_G = 0.05, 5.0
DEFAULT_DENSITY = 1.24   # g/cm³ (PLA) when only a length is known


def required_grams(meta: dict):
    """Slicer weight if present, else length × area × density. None if neither."""
    w = meta.get("filament_weight_total")
    if isinstance(w, (int, float)) and w > 0:
        return float(w)
    mm = meta.get("filament_total")
    if isinstance(mm, (int, float)) and mm > 0:
        area_cm2 = math.pi * (0.175 / 2) ** 2
        return mm / 10.0 * area_cm2 * DEFAULT_DENSITY
    return None


def plan(required_g, remaining_g, source):
    if required_g is None:
        return {"verdict": "unknown", "reason": "no filament figure in the file metadata"}
    if remaining_g is None:
        return {"verdict": "unknown", "reason": "no spool data (connect the sensor or set the virtual spool)",
                "required_g": round(required_g, 1)}
    needed = required_g * (1 + MARGIN_FRACTION) + MARGIN_G
    return {"verdict": "ok" if remaining_g >= needed else "insufficient", "required_g": round(required_g, 1),
            "remaining_g": round(remaining_g, 1), "needed_with_margin_g": round(needed, 1),
            "short_by_g": round(max(0.0, needed - remaining_g), 1), "source": source}


class SpoolPlanner:
    def __init__(self, get_meta=None, get_remaining=None, notify=notify_safe):
        self._get_meta = get_meta or self._moonraker_meta
        self._get_remaining = get_remaining or self._remaining
        self.notify = notify
        self.history = deque(maxlen=20)
        self._was_printing = False

    @staticmethod
    def _moonraker_meta(filename):
        from urllib.parse import quote
        from config.settings import settings
        return http_json(f"{settings.moonraker_url}/server/files/metadata?filename={quote(filename)}",
                         timeout=3).get("result", {})

    @staticmethod
    def _remaining():
        try:
            from plugins.filament_sensor import bridge
            s = bridge.summary()
            if s["connected"] and isinstance(s.get("spool_remaining_g"), (int, float)):
                return float(s["spool_remaining_g"]), "sensor"
        except Exception:  # noqa: BLE001
            pass
        try:
            from db.models import get_connection
            conn = get_connection()
            try:
                cfg = dict(conn.execute("SELECT key, value FROM printer_config").fetchall())
            finally:
                conn.close()
            if "virtual_spool_weight_g" in cfg:
                return float(cfg["virtual_spool_weight_g"]) - float(cfg.get("virtual_spool_used_g", 0)), "virtual spool"
        except Exception:  # noqa: BLE001
            pass
        return None, None

    def check(self, filename):
        try:
            req = required_grams(self._get_meta(filename) or {})
        except Exception:  # noqa: BLE001
            req = None
        rem, src = self._get_remaining()
        result = {"filename": filename, **plan(req, rem, src), "ts": time.time()}
        self.history.appendleft(result)
        return result

    def tick(self, snap, ctx):
        printing = snap.get("print_state") == "printing"
        if printing and not self._was_printing and snap.get("filename"):
            r = self.check(snap["filename"])
            if r["verdict"] == "insufficient":
                self.notify(f"🧵 Indus3D: spool may run out — {r['filename']} needs ~{r['needed_with_margin_g']} g, "
                            f"{r['remaining_g']} g left ({r['source']}). Short by {r['short_by_g']} g.")
        self._was_printing = printing


planner = SpoolPlanner()


def register_hooks(hooks) -> None:
    hooks.on("tick", planner.tick, priority=72)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("plugin_spool_planner", __name__, url_prefix="/api/v1/plugins/spool_planner")

    @bp.route("", methods=["GET"])
    def spool_check():
        fn = request.args.get("filename")
        if not fn:
            return jsonify({"history": list(planner.history)})
        return jsonify(planner.check(fn))

    app.register_blueprint(bp)
