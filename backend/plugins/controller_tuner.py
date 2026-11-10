"""
plugins/controller_tuner.py  (D4)
----------------------------------
Reads how the controller behaved over recent prints and SUGGESTS tuning
changes. It never applies anything: the output is advice with the numbers that
led to it, for a human to act on.

Per print and per family it measures the command rate, direction reversals
(chatter) and how often the command sat at a clamp (flow 85/115 %, speed 50 %).
Rules:
  * chatter      > 1 reversal/min        -> lower the gain or widen the deadband
  * flow clamped > 25 % of commands      -> the slicer flow / E-steps is off;
                                            fix the cause instead of letting M221 compensate
  * speed floored > 20 % of commands     -> the printer cannot keep up at the sliced speed/accel
  * speed rate   > 6/min                 -> raise the lag deadband
  * vetoed >= applied                    -> another controller or guard owns that family

GET /api/v1/plugins/controller_tuner
"""

from collections import deque

PLUGIN_INFO = {
    "title": "Controller tuner",
    "description": "Advice (never applied) on controller gains and deadbands from observed behaviour.",
}

FLOW_MIN, FLOW_MAX, SPEED_MIN = 85.0, 115.0, 50.0
REVERSAL_MIN_DELTA = {"flow": 1.0, "speed": 1.0, "nozzle_temp": 1.0}


def _reversals(values, min_delta):
    last, rev = 0, 0
    for a, b in zip(values, values[1:]):
        d = b - a
        if abs(d) < min_delta:
            continue
        s = 1 if d > 0 else -1
        if last and s != last:
            rev += 1
        last = s
    return rev


def analyse(run: dict) -> dict:
    dur_min = max(((run.get("ended") or run["started"]) - run["started"]) / 60.0, 1e-6)
    by_fam = {}
    for c in run.get("commands", []):
        if c.get("ok") and c.get("family"):
            by_fam.setdefault(c["family"], []).append(c)
    vet = {}
    for v in run.get("vetoes", []):
        from plugins.arbiter import family_of
        vet[family_of(v["command"]) or "other"] = vet.get(family_of(v["command"]) or "other", 0) + 1

    stats = {}
    for fam, cmds in by_fam.items():
        vals = [c["value"] for c in cmds if c.get("value") is not None]
        s = {"commands": len(cmds), "per_min": round(len(cmds) / dur_min, 2)}
        if fam in REVERSAL_MIN_DELTA and vals:
            s["reversals_per_min"] = round(_reversals(vals, REVERSAL_MIN_DELTA[fam]) / dur_min, 2)
        if fam == "flow" and vals:
            s["clamped_fraction"] = round(sum(v <= FLOW_MIN + 0.5 or v >= FLOW_MAX - 0.5 for v in vals) / len(vals), 2)
        if fam == "speed" and vals:
            s["floored_fraction"] = round(sum(v <= SPEED_MIN + 0.5 for v in vals) / len(vals), 2)
        stats[fam] = s

    tips = []
    for fam, s in stats.items():
        if s.get("reversals_per_min", 0) > 1.0:
            tips.append({"family": fam, "rule": "chatter", "evidence": f"{s['reversals_per_min']} reversals/min",
                         "advice": f"The {fam} loop is chattering: lower its gain or widen its deadband "
                                   f"(quality_controller {'FLOW_KP / FLOW_DEADBAND' if fam == 'flow' else 'SPEED_KP / SPEED_DEADBAND'})."})
    f = stats.get("flow", {})
    if f.get("clamped_fraction", 0) > 0.25 and f["commands"] >= 4:
        tips.append({"family": "flow", "rule": "flow_clamped",
                     "evidence": f"{int(f['clamped_fraction'] * 100)}% of M221 commands at the 85/115 % limit",
                     "advice": "The controller keeps hitting its flow limits. Recalibrate the slicer flow ratio / "
                               "extruder rotation_distance rather than letting M221 compensate."})
    sp = stats.get("speed", {})
    if sp.get("floored_fraction", 0) > 0.20 and sp["commands"] >= 4:
        tips.append({"family": "speed", "rule": "speed_floored",
                     "evidence": f"{int(sp['floored_fraction'] * 100)}% of M220 commands at the 50 % floor",
                     "advice": "Speed is repeatedly cut to the floor: lower the sliced speed/acceleration or check belt tension."})
    if sp.get("per_min", 0) > 6:
        tips.append({"family": "speed", "rule": "speed_rate", "evidence": f"{sp['per_min']} commands/min",
                     "advice": "Raise SPEED_DEADBAND so small lag fluctuations do not trigger M220."})
    for fam, n in vet.items():
        applied = stats.get(fam, {}).get("commands", 0)
        if n >= max(1, applied):
            tips.append({"family": fam, "rule": "vetoed",
                         "evidence": f"{n} vetoed vs {applied} applied",
                         "advice": f"Most {fam} corrections are being dropped (arbiter/guard/approval): "
                                   "tuning the controller will not help until that is resolved."})
    return {"run": run["id"], "filename": run.get("filename"), "minutes": round(dur_min, 1),
            "stats": stats, "suggestions": tips}


class Tuner:
    def __init__(self):
        self.reports = deque(maxlen=20)

    def on_finish(self, run):
        if len(run.get("commands", [])) or run.get("vetoes"):
            self.reports.appendleft(analyse(run))

    def recurring(self):
        """Suggestions that appeared in at least two of the last five prints."""
        counts, last = {}, {}
        for r in list(self.reports)[:5]:
            for t in r["suggestions"]:
                key = (t["family"], t["rule"])
                counts[key] = counts.get(key, 0) + 1
                last[key] = t
        return [{**last[k], "seen_in_prints": n} for k, n in counts.items() if n >= 2]


tuner = Tuner()


def register_hooks(hooks) -> None:
    from plugins.run_recorder import recorder
    recorder.on_finish(tuner.on_finish)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_controller_tuner", __name__, url_prefix="/api/v1/plugins/controller_tuner")

    @bp.route("", methods=["GET"])
    def tuner_status():
        return jsonify({"note": "Suggestions only; nothing is applied automatically.",
                        "recurring": tuner.recurring(), "reports": list(tuner.reports)})

    app.register_blueprint(bp)
