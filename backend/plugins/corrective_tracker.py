"""
plugins/corrective_tracker.py  (A3)
------------------------------------
In-process version of helpers/trackers/corrective_gcode_tracker.py: a live
ring buffer plus a JSONL trail of everything the control pipeline did
(applied, failed, vetoed, shadow, correction reasons), and a /diagnose
endpoint that explains why corrective G-code is or is not being sent.

Trail: <plugin data dir>/tracker/corrective_gcode.jsonl (rotated at 5 MB).

GET /api/v1/plugins/corrective_tracker            recent events + counters
GET /api/v1/plugins/corrective_tracker/diagnose   checklist (OK / WARN / FAIL)
"""

import json
import os
import time
from collections import Counter, deque

from plugins._common import data_dir, latest_telemetry
from plugins.arbiter import family_of

PLUGIN_INFO = {
    "title": "Corrective G-code tracker",
    "description": "Live trail of every command, veto and shadow command, plus a 'why is nothing being sent?' diagnosis.",
}

ROTATE_BYTES = 5 * 1024 * 1024
SILENCE_S = 120.0


class Tracker:
    def __init__(self, path=None):
        self.events = deque(maxlen=500)
        self.counts = Counter()
        self.last_applied = None
        self._path = path

    def _file(self):
        return self._path or (data_dir("tracker") / "corrective_gcode.jsonl")

    def _write(self, rec):
        self.events.appendleft(rec)
        try:
            p = self._file()
            if os.path.exists(p) and os.path.getsize(p) > ROTATE_BYTES:
                os.replace(p, str(p) + ".1")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def on_sent(self, results, ctx):
        now = ctx.get("now", time.time())
        for r in results:
            kind = "applied" if r.get("ok") else "failed"
            self.counts[kind] += 1
            if r.get("ok"):
                self.last_applied = now
            self._write({"t": now, "kind": kind, "command": r["command"],
                         "family": family_of(r["command"]), "source": ctx.get("source")})
        for c in ctx.get("corrections", []):
            self._write({"t": now, "kind": "correction", **{k: c.get(k) for k in ("type", "value", "reason")}})

    def on_vetoed(self, vetoes, ctx):
        for v in vetoes:
            self.counts["vetoed"] += 1
            self._write({"t": ctx.get("now", time.time()), "kind": "vetoed", "command": v["command"],
                         "plugin": v["plugin"], "reason": v["reason"]})

    def on_shadow(self, commands, ctx):
        for c in commands:
            self.counts["shadow"] += 1
            self._write({"t": ctx.get("now", time.time()), "kind": "shadow", "command": c,
                         "family": family_of(c)})

    def status(self):
        return {"counts": dict(self.counts), "last_applied": self.last_applied, "events": list(self.events)[:200]}


tracker = Tracker()


def diagnose(telemetry: dict, autopilot: bool, shadow_enabled: bool, tr: Tracker = None,
             watchdog_tripped=None, approval=None, guard_blocked=0, now=None) -> list:
    """Pure function: [(level, check, detail)]."""
    tr, now = tr or tracker, now or time.time()
    rows = []
    state = telemetry.get("print_state", "unknown")
    printing = state == "printing"
    if autopilot:
        rows.append(("OK", "auto-pilot", "enabled"))
    else:
        rows.append(("FAIL", "auto-pilot",
                     "DISABLED — the controller sends no corrective G-code. "
                     + ("Shadow mode is recording what it would send."
                        if shadow_enabled else "Enable shadow_mode to see what it would send.")))
    rows.append(("OK" if printing else "WARN", "print state",
                 "printing" if printing else f"'{state}' — corrections are only produced while printing"))
    if watchdog_tripped:
        rows.append(("FAIL", "watchdog", f"tripped: {watchdog_tripped.get('reason')} — corrections blocked until re-armed"))
    if approval and approval.get("enabled"):
        rows.append(("WARN", "approval mode", f"{len(approval.get('pending', []))} command(s) waiting for approval"))
    if guard_blocked:
        rows.append(("WARN", "first-layer guard", f"has held back {guard_blocked} command(s)"))
    if autopilot and printing:
        age = None if tr.last_applied is None else now - tr.last_applied
        if age is None or age > SILENCE_S:
            rows.append(("WARN", "silence", "auto-pilot on and printing but no command applied in "
                         f"{'this session' if age is None else f'{age:.0f}s'} — the controller may simply see nothing to fix"))
    c = tr.counts
    rows.append(("OK" if c["applied"] or c["shadow"] else "WARN", "activity",
                 f"applied={c['applied']} failed={c['failed']} vetoed={c['vetoed']} shadow={c['shadow']}"))
    if c["vetoed"] and c["vetoed"] >= max(1, c["applied"]):
        rows.append(("WARN", "vetoes", "plugins drop at least as many commands as are sent — see recent events"))
    return rows


def register_hooks(hooks) -> None:
    hooks.on("commands.sent", tracker.on_sent, priority=92)
    hooks.on("commands.vetoed", tracker.on_vetoed, priority=92)
    hooks.on("shadow.commands", tracker.on_shadow, priority=92)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_corrective_tracker", __name__, url_prefix="/api/v1/plugins/corrective_tracker")

    @bp.route("", methods=["GET"])
    def tracker_status():
        return jsonify(tracker.status())

    @bp.route("/diagnose", methods=["GET"])
    def tracker_diagnose():
        from digital_twin.quality_controller import quality_controller as qc
        wd = ap = guard = None
        try:
            from plugins.watchdog import watchdog
            wd = watchdog.tripped
            from plugins.approval import approval
            ap = approval.status()
            from plugins.first_layer_guard import guard as g
            guard = g.blocked_total
        except Exception:  # noqa: BLE001
            pass
        rows = diagnose(latest_telemetry(), qc.auto_pilot, qc.shadow_enabled, tracker, wd, ap, guard or 0)
        return jsonify([{"level": l, "check": c, "detail": d} for l, c, d in rows])

    app.register_blueprint(bp)
