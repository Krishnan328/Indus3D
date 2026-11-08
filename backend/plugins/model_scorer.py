"""
plugins/model_scorer.py  (D2)
------------------------------
After every print, compares what Indus3D / the slicer predicted with what
happened, so you can see how far each model can be trusted on YOUR printer:

  print time      slicer estimate (Moonraker file metadata) vs actual duration
  filament mass   slicer estimate vs print_history.filament_used_g
  hotend tracking RMS / max deviation from the target while printing

Errors are signed percentages (+ = reality exceeded the prediction) with an
"ok" tolerance of ±10 %. The result is stored in the plugin data dir and in
action_log (alert_id "model_score"). Evaluation runs a few seconds after the
print ends because print_history is written by the telemetry worker then.

GET /api/v1/plugins/model_scorer
"""

import logging
import time
from collections import deque

from plugins._common import delayed, data_dir, http_json, read_json, write_json

PLUGIN_INFO = {
    "title": "Model-vs-reality scorer",
    "description": "Signed prediction error for print time, filament and hotend tracking after each print.",
}

TOLERANCE_PCT = 10.0
EVAL_DELAY_S = 6.0


def _pct(actual, predicted):
    if not predicted or actual is None:
        return None
    return round((actual - predicted) / predicted * 100.0, 1)


def _row(name, predicted, actual, unit):
    err = _pct(actual, predicted)
    return {"metric": name, "predicted": predicted, "actual": actual, "unit": unit, "error_pct": err,
            "status": None if err is None else ("ok" if abs(err) <= TOLERANCE_PCT else "off")}


def score_run(run: dict, meta: dict, history_row: dict) -> dict:
    """Pure: build the score from a run, Moonraker metadata and a print_history row."""
    duration = (run["ended"] - run["started"]) if run.get("ended") else None
    rows = [
        _row("print_time", meta.get("estimated_time"), duration, "s"),
        _row("filament_mass", meta.get("filament_weight_total"), (history_row or {}).get("filament_used_g"), "g"),
    ]
    n = run.get("temp_samples", 0)
    if n:
        rms = (run["temp_err_sq"] / n) ** 0.5
        rows.append({"metric": "hotend_tracking", "predicted": 0.0, "actual": round(rms, 2), "unit": "°C RMS",
                     "error_pct": None, "status": "ok" if rms <= 3.0 else "off",
                     "max_deviation_c": round(run.get("max_temp_err", 0.0), 1)})
    return {"run": run["id"], "filename": run.get("filename"), "final_state": run.get("final_state"),
            "metrics": rows,
            "overall": "ok" if all(r["status"] in (None, "ok") for r in rows) else "off"}


class Scorer:
    def __init__(self, fetch_meta=None, fetch_history=None, write_action=None):
        self.results = deque(maxlen=50)
        self._fetch_meta = fetch_meta or self._default_meta
        self._fetch_history = fetch_history or self._default_history
        self._write_action = write_action or self._default_write

    @staticmethod
    def _default_meta(filename):
        from config.settings import settings
        if not filename:
            return {}
        r = http_json(f"{settings.moonraker_url}/server/files/metadata?filename={filename}", timeout=3)
        return r.get("result", {})

    @staticmethod
    def _default_history(run):
        from db.models import get_connection
        conn = get_connection()
        try:
            row = conn.execute("SELECT filament_used_g, print_time_seconds FROM print_history "
                               "WHERE filename=? ORDER BY id DESC LIMIT 1", (run.get("filename"),)).fetchone()
        finally:
            conn.close()
        return {"filament_used_g": row[0], "print_time_seconds": row[1]} if row else {}

    @staticmethod
    def _default_write(row):
        from db.models import get_connection
        conn = get_connection()
        try:
            conn.execute("INSERT INTO action_log (timestamp, alert_id, gcode, description, status) "
                         "VALUES (?, ?, ?, ?, ?)", row)
            conn.commit()
        finally:
            conn.close()

    def evaluate(self, run):
        try:
            meta = self._fetch_meta(run.get("filename"))
        except Exception as e:  # noqa: BLE001 — Moonraker offline / simulator
            logging.info(f"model_scorer: no slicer metadata ({e})")
            meta = {}
        try:
            hist = self._fetch_history(run)
        except Exception:  # noqa: BLE001
            hist = {}
        result = score_run(run, meta, hist)
        result["scored_at"] = time.time()
        self.results.appendleft(result)
        try:
            write_json(data_dir("scores") / f"score-{run['id']}.json", result)
            desc = "; ".join(f"{m['metric']}: {m['error_pct']}%" if m["error_pct"] is not None
                             else f"{m['metric']}: {m['actual']} {m['unit']}" for m in result["metrics"])
            self._write_action((time.time(), "model_score", result["overall"], desc, "final"))
        except Exception as e:  # noqa: BLE001
            logging.info(f"model_scorer: could not persist: {e}")
        return result

    def on_finish(self, run):
        delayed(EVAL_DELAY_S, self.evaluate, run)


scorer = Scorer()


def register_hooks(hooks) -> None:
    from plugins.run_recorder import recorder
    recorder.on_finish(scorer.on_finish)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_model_scorer", __name__, url_prefix="/api/v1/plugins/model_scorer")

    @bp.route("", methods=["GET"])
    def scores():
        stored = [read_json(p, None) for p in sorted(data_dir("scores").glob("score-*.json"))[-20:]]
        results = list(scorer.results) or [s for s in reversed(stored) if s]
        return jsonify({"tolerance_pct": TOLERANCE_PCT, "results": results})

    app.register_blueprint(bp)
