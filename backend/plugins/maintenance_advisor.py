"""
plugins/maintenance_advisor.py  (G2)
--------------------------------------
Builds on the maintenance counters the telemetry worker already keeps
(odometry, heat cycles, nozzle and filter hours) and the rules behind
/api/v1/maintenance:

* percent of each limit used, status ok / soon (>= 80 %) / due (>= 100 %),
* a projection of PRINT hours left, from the average usage per print hour so
  far (shown only with a usable rate),
* one notification per item when it first reaches 90 % ("soon") and again
  when due (remembered across restarts in the plugin data dir; resetting a
  counter re-arms it).

The projection assumes future wear per print hour matches the past; it is a
planning aid, not a guarantee.

GET /api/v1/plugins/maintenance_advisor
"""

from plugins._common import data_dir, notify_safe, read_json, write_json

PLUGIN_INFO = {
    "title": "Maintenance advisor",
    "description": "Usage vs limits, projected print hours left, and one-time alerts as parts come due.",
}

SOON_PCT, NOTIFY_PCT = 80.0, 90.0


def assess(rules: list, counters: dict, total_print_hours: float) -> list:
    out = []
    for r in rules:
        val = float(counters.get(r["metric"], 0.0))
        thr = float(r["threshold"])
        pct = val / thr * 100 if thr else 0.0
        item = {"metric": r["metric"], "msg": r["msg"], "type": r.get("type"), "value": round(val, 2),
                "threshold": thr, "percent_used": round(pct, 1),
                "status": "due" if pct >= 100 else "soon" if pct >= SOON_PCT else "ok",
                "print_hours_left": None}
        if total_print_hours >= 1.0 and val > 0 and pct < 100:
            rate = val / total_print_hours
            item["print_hours_left"] = round((thr - val) / rate, 1)
        out.append(item)
    return out


class Advisor:
    def __init__(self, load=None, notify=notify_safe, state_path=None):
        self._load = load or self._from_db
        self.notify = notify
        self._state_path = state_path

    @staticmethod
    def _from_db():
        from api.server import get_maintenance_rules      # lazy: api.server imports the plugin loader
        from db.models import get_connection
        conn = get_connection()
        try:
            counters = dict(conn.execute("SELECT task_id, value FROM maintenance_counters").fetchall())
            secs = conn.execute("SELECT COALESCE(SUM(print_time_seconds), 0) FROM print_history").fetchone()[0]
        finally:
            conn.close()
        return get_maintenance_rules(), counters, (secs or 0) / 3600.0

    def _state_file(self):
        return self._state_path or (data_dir() / "maintenance_notified.json")

    def report(self, notify=False):
        rules, counters, hours = self._load()
        items = assess(rules, counters, hours)
        if notify:
            self._notify_new(items)
        return {"total_print_hours": round(hours, 1), "items": items}

    def _notify_new(self, items):
        state = read_json(self._state_file(), {})
        changed = False
        for it in items:
            level = "due" if it["status"] == "due" else ("soon" if it["percent_used"] >= NOTIFY_PCT else None)
            prev = state.get(it["metric"])
            if level is None:
                if prev:                                  # counter was reset: re-arm
                    state.pop(it["metric"], None)
                    changed = True
                continue
            if prev != level and not (prev == "due" and level == "soon"):
                state[it["metric"]] = level
                changed = True
                self.notify(f"🔧 Indus3D maintenance ({level}): {it['msg']} — {it['percent_used']}% of limit used")
        if changed:
            write_json(self._state_file(), state)

    def on_finish(self, run):
        try:
            self.report(notify=True)
        except Exception:  # noqa: BLE001 — counters may not exist yet (fresh DB / simulator)
            pass


advisor = Advisor()


def register_hooks(hooks) -> None:
    from plugins.run_recorder import recorder
    recorder.on_finish(advisor.on_finish)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_maintenance_advisor", __name__, url_prefix="/api/v1/plugins/maintenance_advisor")

    @bp.route("", methods=["GET"])
    def maint():
        try:
            return jsonify(advisor.report())
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": f"maintenance data unavailable: {e}"}), 503

    app.register_blueprint(bp)
