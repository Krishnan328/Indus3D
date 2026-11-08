"""
plugins/slicer_feedback.py  (F2)
---------------------------------
Turns what the controller actually did into suggested SLICER profile changes,
per material. After each print it records the time-weighted average flow
(M221, starting from 100 %) and the average pressure advance sent. With at
least 3 prints of a material and consistent behaviour it suggests:

  flow multiplier   mean applied flow / 100 — multiply your slicer's flow ratio
                    (OrcaSlicer `filament_flow_ratio`, PrusaSlicer
                    `extrusion_multiplier`) by it; shown only if it differs by
                    >= 1.5 % and the per-print values agree (stdev <= 3 %)
  pressure advance  mean SET_PRESSURE_ADVANCE value

Caveats: flow is only meaningful when the auto-pilot was on; the pressure
advance values mostly echo the configured linear_advance_k, so treat that one
as a cross-check, not a calibration. Nothing is written to your slicer.

GET /api/v1/plugins/slicer_feedback[?material=PLA]
GET /api/v1/plugins/slicer_feedback/export?format=orca|prusa|json&material=PLA
"""

import statistics

from plugins._common import active_material, data_dir, read_json, write_json

PLUGIN_INFO = {
    "title": "Slicer feedback export",
    "description": "Suggested slicer flow/PA changes from observed controller behaviour, per material.",
}

MIN_RUNS = 3
MIN_FLOW_DELTA_PCT = 1.5
MAX_FLOW_STDEV = 3.0
_FILE = "slicer_feedback.json"


def observe(run: dict):
    """(time-weighted mean flow %, mean PA or None, applied flow cmds, applied PA cmds)."""
    t0, t1 = run["started"], run.get("ended") or run["started"]
    flow = [(c["t"], c["value"]) for c in run.get("commands", [])
            if c.get("ok") and c.get("family") == "flow" and c.get("value") is not None]
    mean = None
    if flow and t1 > t0:
        total, last_t, last_v = 0.0, t0, 100.0
        for t, v in flow:
            t = min(max(t, t0), t1)
            total += last_v * (t - last_t)
            last_t, last_v = t, v
        total += last_v * (t1 - last_t)
        mean = total / (t1 - t0)
    pa = [c["value"] for c in run.get("commands", [])
          if c.get("ok") and c.get("family") == "pa" and c.get("value") is not None]
    return mean, (sum(pa) / len(pa) if pa else None), len(flow), len(pa)


def suggest(observations: list) -> dict:
    flows = [o["flow_avg"] for o in observations if o.get("flow_avg") is not None]
    pas = [o["pa_mean"] for o in observations if o.get("pa_mean") is not None]
    out = {"runs": len(observations), "flow": None, "pressure_advance": None, "notes": []}
    if len(flows) >= MIN_RUNS:
        mean = statistics.mean(flows)
        sd = statistics.pstdev(flows)
        if sd > MAX_FLOW_STDEV:
            out["notes"].append(f"flow varies too much between prints (stdev {sd:.1f} %) for a reliable suggestion")
        elif abs(mean - 100) >= MIN_FLOW_DELTA_PCT:
            out["flow"] = {"multiplier": round(mean / 100.0, 4), "mean_applied_pct": round(mean, 1),
                           "stdev_pct": round(sd, 2)}
        else:
            out["notes"].append("average applied flow is within 1.5 % of 100 %: no flow change suggested")
    else:
        out["notes"].append(f"need {MIN_RUNS} prints with flow corrections (have {len(flows)})")
    if len(pas) >= MIN_RUNS:
        out["pressure_advance"] = {"mean": round(statistics.mean(pas), 4), "stdev": round(statistics.pstdev(pas), 4)}
    return out


def render(fmt: str, material: str, s: dict) -> str:
    flow = (s.get("flow") or {}).get("multiplier")
    pa = (s.get("pressure_advance") or {}).get("mean")
    if fmt == "json":
        return None
    lines = [f"# Indus3D suggestion for {material} ({s['runs']} prints) — review before use"]
    if fmt == "orca":
        lines.append(f"# flow: multiply filament_flow_ratio by {flow}" if flow else "# flow: no change suggested")
        if pa is not None:
            lines += ["enable_pressure_advance = 1", f"pressure_advance = {pa}"]
    else:  # prusa
        lines.append(f"# flow: multiply extrusion_multiplier by {flow}" if flow else "# flow: no change suggested")
        if pa is not None:
            lines.append(f"; M572 / SET_PRESSURE_ADVANCE ADVANCE={pa}   (start gcode)")
    return "\n".join(lines) + "\n"


class Feedback:
    def __init__(self, path=None):
        self._path = path

    def _file(self):
        return self._path or (data_dir() / _FILE)

    def data(self):
        return read_json(self._file(), {})

    def on_finish(self, run, material=None):
        if run.get("final_state") != "complete":
            return                                  # cancelled/failed prints say nothing about steady state
        flow, pa, nflow, npa = observe(run)
        if flow is None and pa is None:
            return
        material = material or active_material()
        d = self.data()
        d.setdefault(material, []).append({"run": run["id"], "flow_avg": flow, "pa_mean": pa,
                                           "flow_cmds": nflow, "pa_cmds": npa})
        d[material] = d[material][-20:]
        write_json(self._file(), d)

    def report(self, material=None):
        d = self.data()
        mats = [material] if material else sorted(d)
        return {m: {"suggestion": suggest(d.get(m, [])), "observations": d.get(m, [])} for m in mats}


feedback = Feedback()


def register_hooks(hooks) -> None:
    from plugins.run_recorder import recorder
    recorder.on_finish(feedback.on_finish)


def register_routes(app) -> None:
    from flask import Blueprint, Response, jsonify, request

    bp = Blueprint("plugin_slicer_feedback", __name__, url_prefix="/api/v1/plugins/slicer_feedback")

    @bp.route("", methods=["GET"])
    def fb():
        return jsonify(feedback.report(request.args.get("material")))

    @bp.route("/export", methods=["GET"])
    def export():
        fmt = request.args.get("format", "json")
        if fmt not in ("json", "orca", "prusa"):
            return jsonify({"error": "format must be orca, prusa or json"}), 400
        material = request.args.get("material") or active_material()
        s = feedback.report(material)[material]["suggestion"]
        text = render(fmt, material, s)
        return jsonify({"material": material, **s}) if text is None else Response(text, mimetype="text/plain")

    app.register_blueprint(bp)
