"""
plugins/run_recorder.py
------------------------
Foundation for the analysis plugins: records what the controller did during
each print (applied commands, vetoes, shadow commands, correction reasons,
progress, hotend tracking error) and tells subscribers when a print ends.

Other plugins import ``recorder`` and either read ``recorder.current`` /
``recorder.history`` or register ``recorder.on_finish(fn)``. Finished runs are
also archived as JSON in the plugin data dir (last 30 kept).

GET /api/v1/plugins/run_recorder          summaries of current + recent runs
GET /api/v1/plugins/run_recorder/<id>     one full run
"""

import logging
import time
from collections import deque
from typing import Callable, List, Optional

from core.job_tracker import is_new_job, job_ref
from plugins._common import data_dir, read_json, write_json
from plugins.arbiter import family_of, s_value

PLUGIN_INFO = {
    "title": "Run recorder",
    "description": "Records per-print controller activity; the base for reports, scoring, tuning and timelines.",
}

MAX_EVENTS = 2000
KEEP = 30
SAMPLE_EVERY_S = 1.0


class RunRecorder:
    def __init__(self, archive=True):
        self.current: Optional[dict] = None
        self.history: deque = deque(maxlen=KEEP)
        self._listeners: List[Callable[[dict], None]] = []
        self._next_id = int(time.time())
        self._last_sample = float("-inf")
        self._archive = archive
        self._printing = False
        self._ref: Optional[dict] = None

    def on_finish(self, fn: Callable[[dict], None]) -> None:
        self._listeners.append(fn)

    # -- lifecycle ----------------------------------------------------------
    def _start(self, snap, now):
        self._next_id += 1
        self.current = {
            "id": self._next_id, "filename": snap.get("filename", ""), "started": now, "ended": None,
            "final_state": None, "progress": 0.0,
            "commands": [], "vetoes": [], "shadow": [], "corrections": [],
            "temp_err_sq": 0.0, "temp_samples": 0, "max_temp_err": 0.0,
        }
        self._last_sample = float("-inf")

    def _finish(self, state, now):
        run, self.current = self.current, None
        if not run:
            return
        run["ended"], run["final_state"] = now, state
        self.history.appendleft(run)
        if self._archive:
            try:
                write_json(data_dir("runs") / f"run-{run['id']}.json", run)
                files = sorted(data_dir("runs").glob("run-*.json"))
                for old in files[:-KEEP]:
                    old.unlink(missing_ok=True)
            except OSError as e:
                logging.info(f"⚠️  run_recorder: could not archive run: {e}")
        for fn in list(self._listeners):
            try:
                fn(run)
            except Exception as e:  # noqa: BLE001
                logging.error(f"run_recorder listener failed: {e}")

    # -- hooks --------------------------------------------------------------
    def tick(self, snap, ctx):
        now = ctx.get("now", time.time())
        printing = snap.get("print_state") in ("printing", "paused")
        if printing and self._printing and is_new_job(self._ref, snap):
            # queued job right behind the previous one (no non-printing tick in between): close the old
            # run and open a new one so commands/vetoes/corrections are not mixed across prints
            self._finish("complete", now)
            self._start(snap, now)
        elif printing and not self._printing:
            self._start(snap, now)
        elif self._printing and not printing:
            self._finish(snap.get("print_state", "unknown"), now)
        self._printing = printing
        self._ref = job_ref(snap) if printing else None
        run = self.current
        if not run:
            return
        run["progress"] = snap.get("progress", run["progress"])
        if now - self._last_sample >= SAMPLE_EVERY_S:
            self._last_sample = now
            t, g = snap.get("ext_temp"), snap.get("ext_target")
            if t is not None and g:
                err = abs(t - g)
                run["temp_err_sq"] += err * err
                run["temp_samples"] += 1
                run["max_temp_err"] = max(run["max_temp_err"], err)

    def _cap(self, key, items):
        run = self.current
        if run is None:
            return
        run[key].extend(items)
        if len(run[key]) > MAX_EVENTS:
            del run[key][: len(run[key]) - MAX_EVENTS]

    def on_sent(self, results, ctx):
        run = self.current
        if not run:
            return
        prog = (ctx.get("snap") or {}).get("progress", run["progress"])
        self._cap("commands", [
            {"t": r.get("ts", ctx.get("now")), "command": r["command"], "family": family_of(r["command"]),
             "value": s_value(r["command"]), "ok": bool(r.get("ok")), "progress": prog,
             "source": ctx.get("source")} for r in results])
        self._cap("corrections", [{**c, "progress": prog} for c in ctx.get("corrections", [])])

    def on_vetoed(self, vetoes, ctx):
        self._cap("vetoes", [{"t": ctx.get("now"), **v} for v in vetoes])

    def on_shadow(self, commands, ctx):
        run = self.current
        if not run:
            return
        prog = (ctx.get("snap") or {}).get("progress", run["progress"])
        self._cap("shadow", [{"t": ctx.get("now"), "command": c, "family": family_of(c),
                              "value": s_value(c), "progress": prog} for c in commands])

    # -- views --------------------------------------------------------------
    @staticmethod
    def summary(run: dict) -> dict:
        n = run["temp_samples"]
        return {
            "id": run["id"], "filename": run["filename"], "started": run["started"], "ended": run["ended"],
            "final_state": run["final_state"], "progress": run["progress"],
            "commands": len(run["commands"]), "vetoes": len(run["vetoes"]), "shadow": len(run["shadow"]),
            "temp_rms_error_c": round((run["temp_err_sq"] / n) ** 0.5, 2) if n else None,
        }

    def get(self, run_id) -> Optional[dict]:
        if self.current and (run_id in ("current", self.current["id"])):
            return self.current
        for r in self.history:
            if r["id"] == run_id:
                return r
        stored = read_json(data_dir("runs") / f"run-{run_id}.json", None)
        return stored


recorder = RunRecorder()


def register_hooks(hooks) -> None:
    hooks.on("tick", recorder.tick, priority=5)
    hooks.on("commands.sent", recorder.on_sent, priority=85)
    hooks.on("commands.vetoed", recorder.on_vetoed, priority=85)
    hooks.on("shadow.commands", recorder.on_shadow, priority=85)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_run_recorder", __name__, url_prefix="/api/v1/plugins/run_recorder")

    @bp.route("", methods=["GET"])
    def runs():
        return jsonify({"current": recorder.summary(recorder.current) if recorder.current else None,
                        "recent": [recorder.summary(r) for r in recorder.history]})

    @bp.route("/<run_id>", methods=["GET"])
    def run_detail(run_id):
        key = run_id if run_id == "current" else (int(run_id) if run_id.isdigit() else None)
        run = recorder.get(key) if key is not None else None
        return (jsonify(run), 200) if run else (jsonify({"error": "run not found"}), 404)

    app.register_blueprint(bp)
