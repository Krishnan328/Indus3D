"""
plugins/health_score.py  (D3)
------------------------------
One 0-100 number per print, with the reasons, from signals Indus3D already
computes. It starts at 100 and loses points for:

  adhesion   lowest sintering healing degree D_h below 0.95        up to 30
  warpage    peak warpage above 0.35 mm                            up to 25
  nozzle     clog / stripping verdict at any point                 20
  roughness  peak predicted Ra above the 12 µm target              up to 10
  thermal    each thermal-sanity event during the print            5 (max 15)
  watchdog   each watchdog trip during the print                   20 (max 20)
  activity   more than 6 applied corrections per minute            up to 10

The weights are a starting heuristic, not a validated quality metric: use the
score to compare prints on the same printer, and the components to see why.
Controller signals come from the live controller when the auto-pilot is on,
otherwise from the shadow run ("data_source" says which; "none" means the score
is based on nothing but counters). The final score of every print is written to
action_log as alert_id "print_health".

GET /api/v1/plugins/health_score   live score and the last finished print
"""

import logging
import time

PLUGIN_INFO = {
    "title": "Print health score",
    "description": "A per-print 0-100 score with the components that explain it.",
}

ADHESION_OK, WARPAGE_OK, RA_TARGET, RATE_OK = 0.95, 0.35, 12.0, 6.0


def _clamp(v, hi):
    return max(0.0, min(hi, v))


class HealthScore:
    def __init__(self, controller=None, thermal=None, watchdog=None, write_log=None):
        self._controller = controller   # callable -> (source_name, active_dict) ; injectable for tests
        self._thermal = thermal         # callable -> int (cumulative thermal events)
        self._watchdog = watchdog       # callable -> int (cumulative watchdog trips)
        self._write_log = write_log
        self.last_final = None
        self._reset(None)
        self.printing = False

    def _reset(self, now):
        self.started = now
        self.min_adhesion, self.max_warpage, self.max_ra = 1.0, 0.0, 0.0
        self.nozzle_bad = False
        self.applied = 0
        self.source = "none"
        self.base_thermal = self._count(self._thermal)
        self.base_trips = self._count(self._watchdog)
        self._last_sample = float("-inf")   # sample on the first tick

    @staticmethod
    def _count(fn):
        try:
            return int(fn()) if fn else 0
        except Exception:  # noqa: BLE001
            return 0

    def _controller_values(self):
        if self._controller:
            return self._controller()
        from digital_twin.quality_controller import quality_controller as qc
        if qc.auto_pilot:
            return "auto-pilot", qc.active
        if qc._shadow_instance is not None:
            return "shadow", qc._shadow_instance.active
        return "none", {}

    # hooks -------------------------------------------------------------------
    def tick(self, snap, ctx):
        now = ctx.get("now", time.time())
        printing = snap.get("print_state") == "printing"
        if printing and not self.printing:
            self._reset(now)
        if self.printing and not printing:
            self.finalize(now)
        self.printing = printing
        if printing and now - self._last_sample >= 1.0:
            self._last_sample = now
            self.sample()

    def sample(self):
        source, a = self._controller_values()
        self.source = source
        if not a:
            return
        if isinstance(a.get("adhesion_score"), (int, float)):
            self.min_adhesion = min(self.min_adhesion, a["adhesion_score"])
        self.max_warpage = max(self.max_warpage, a.get("warpage_mm") or 0.0)
        self.max_ra = max(self.max_ra, a.get("ra_predicted_um") or 0.0)
        if a.get("nozzle_status") not in (None, "NORMAL"):
            self.nozzle_bad = True

    def on_sent(self, results, ctx):
        if self.printing:
            self.applied += sum(1 for r in results if r.get("ok"))

    # scoring -----------------------------------------------------------------
    def score(self, now=None):
        now = now or time.time()
        dur = max(0.0, now - self.started) if self.started else 0.0
        comps = []

        def add(name, penalty, detail):
            if penalty > 0:
                comps.append({"name": name, "penalty": round(penalty, 1), "detail": detail})

        add("adhesion", _clamp((ADHESION_OK - self.min_adhesion) / ADHESION_OK * 30, 30),
            f"lowest D_h {self.min_adhesion:.2f}")
        add("warpage", _clamp((self.max_warpage - WARPAGE_OK) / WARPAGE_OK * 25, 25),
            f"peak {self.max_warpage:.2f} mm")
        add("nozzle", 20 if self.nozzle_bad else 0, "clog/stripping verdict raised")
        add("roughness", _clamp((self.max_ra - RA_TARGET) / RA_TARGET * 10, 10), f"peak Ra {self.max_ra:.1f} µm")
        thermal = max(0, self._count(self._thermal) - self.base_thermal)
        add("thermal", _clamp(thermal * 5, 15), f"{thermal} thermal-sanity event(s)")
        trips = max(0, self._count(self._watchdog) - self.base_trips)
        add("watchdog", _clamp(trips * 20, 20), f"{trips} watchdog trip(s)")
        rate = self.applied / (dur / 60) if dur >= 60 else 0.0
        add("activity", _clamp((rate - RATE_OK) / RATE_OK * 10, 10), f"{rate:.1f} corrections/min")

        return {"score": round(100 - sum(c["penalty"] for c in comps), 1), "components": comps,
                "data_source": self.source, "duration_s": round(dur, 1),
                "applied_corrections": self.applied}

    def finalize(self, now):
        result = self.score(now)
        self.last_final = {**result, "finished_at": now}
        logging.info(f"💯 print health score: {result['score']} ({result['data_source']})")
        detail = "; ".join(f"{c['name']} -{c['penalty']} ({c['detail']})" for c in result["components"]) or "no penalties"
        row = (now, "print_health", str(result["score"]), f"{detail} [source: {result['data_source']}]", "final")
        try:
            if self._write_log:
                self._write_log(row)
            else:
                from db.models import get_connection
                conn = get_connection()
                try:
                    conn.execute("INSERT INTO action_log (timestamp, alert_id, gcode, description, status) "
                                 "VALUES (?, ?, ?, ?, ?)", row)
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:  # noqa: BLE001
            logging.info(f"⚠️  health_score: could not write action_log: {e}")

    def status(self):
        return {"printing": self.printing, "live": self.score() if self.printing else None,
                "last_final": self.last_final}


def _thermal_total():
    from plugins.thermal_sanity import sanity
    return sanity.total


def _watchdog_trips():
    from plugins.watchdog import watchdog
    return len(watchdog.trips)


health = HealthScore(thermal=_thermal_total, watchdog=_watchdog_trips)


def register_hooks(hooks) -> None:
    hooks.on("tick", health.tick, priority=60)
    hooks.on("commands.sent", health.on_sent, priority=80)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_health_score", __name__, url_prefix="/api/v1/plugins/health_score")

    @bp.route("", methods=["GET"])
    def health_status():
        return jsonify(health.status())

    app.register_blueprint(bp)
