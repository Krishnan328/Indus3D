"""
plugins/fleet_aggregator.py  (F4)
-----------------------------------
One call that summarises every printer in the registry (config/printers.json,
the same list the Fleet page switches between): online/offline, print state,
file, progress, temperatures, and an "attention" flag with the reason
(offline, error, paused, cancelled). Printers are queried in parallel with a
short timeout and cached for 5 s. For the ACTIVE printer the summary also
carries Indus3D's own view (auto-pilot, watchdog trip, print health).

Only Moonraker's read-only status endpoints are used; nothing is sent to any
printer. Remote printers are reported from Moonraker alone: Indus3D's own
analysis only exists for the printer this instance is attached to.

GET /api/v1/plugins/fleet
"""

import time
from concurrent.futures import ThreadPoolExecutor

from plugins._common import http_json

PLUGIN_INFO = {
    "title": "Fleet aggregator",
    "description": "Health summary of every registered printer from Moonraker, plus Indus3D's view of the active one.",
}

CACHE_S = 5.0
QUERY = "print_stats&extruder&heater_bed&display_status"
ATTENTION_STATES = {"error": "printer reports an error", "paused": "print is paused", "cancelled": "print was cancelled"}


def summarize_status(status: dict) -> dict:
    ps, ex, bed, ds = (status.get(k, {}) or {} for k in ("print_stats", "extruder", "heater_bed", "display_status"))
    state = ps.get("state", "unknown")
    return {"online": True, "state": state, "filename": ps.get("filename") or None,
            "progress": round((ds.get("progress") or 0.0) * 100, 1),
            "ext_temp": ex.get("temperature"), "ext_target": ex.get("target"),
            "bed_temp": bed.get("temperature"), "bed_target": bed.get("target"),
            "attention": ATTENTION_STATES.get(state)}


class Fleet:
    def __init__(self, list_printers=None, fetch=None, indus_view=None):
        self._list = list_printers or self._registry
        self._fetch = fetch or (lambda host, port: http_json(
            f"http://{host}:{port}/printer/objects/query?{QUERY}", timeout=2.0)["result"]["status"])
        self._indus = indus_view or self._active_view
        self._cache = (0.0, None)

    @staticmethod
    def _registry():
        from config import printers
        return printers.list_printers()

    @staticmethod
    def _active_view():
        from digital_twin.quality_controller import quality_controller as qc
        view = {"autopilot": bool(qc.auto_pilot)}
        try:
            from plugins.watchdog import watchdog
            view["watchdog_tripped"] = bool(watchdog.tripped)
            from plugins.health_score import health
            view["health_score"] = (health.score()["score"] if health.printing
                                    else (health.last_final or {}).get("score"))
        except Exception:  # noqa: BLE001
            pass
        return view

    def _one(self, p, active_id):
        base = {"id": p["id"], "name": p.get("name", p["id"]), "host": p["host"], "port": p["port"],
                "active": p["id"] == active_id}
        try:
            info = summarize_status(self._fetch(p["host"], p["port"]))
        except Exception as e:  # noqa: BLE001
            info = {"online": False, "state": "offline", "attention": "printer unreachable",
                    "error": f"{type(e).__name__}"}
        if base["active"]:
            info["indus3d"] = self._indus()
            if info["indus3d"].get("watchdog_tripped"):
                info["attention"] = info.get("attention") or "Indus3D watchdog disabled the auto-pilot"
        return {**base, **info}

    def summary(self, now=None):
        now = now or time.time()
        if self._cache[1] is not None and now - self._cache[0] < CACHE_S:
            return self._cache[1]
        reg = self._list()
        printers = reg["printers"]
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(printers)))) as ex:
            rows = list(ex.map(lambda p: self._one(p, reg["active"]), printers))
        out = {"generated": now, "total": len(rows), "online": sum(r["online"] for r in rows),
               "printing": sum(r["state"] == "printing" for r in rows),
               "needs_attention": [{"id": r["id"], "name": r["name"], "reason": r["attention"]}
                                   for r in rows if r.get("attention")],
               "printers": rows}
        self._cache = (now, out)
        return out


fleet = Fleet()


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_fleet", __name__, url_prefix="/api/v1/plugins/fleet")

    @bp.route("", methods=["GET"])
    def fleet_summary():
        return jsonify(fleet.summary())

    app.register_blueprint(bp)
