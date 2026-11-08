"""
plugins/calibration_runner.py  (D1)
-------------------------------------
A guided, reviewable calibration workflow. It does NOT run anything on the
printer: each automatic step names the existing, safety-gated endpoint to call
(they refuse during a print and demand explicit confirmation), and this plugin
keeps the order, records what a human saw and decided, validates the measured
results and turns them into recommendations. Nothing is ever applied by it.

Templates: full, pid, mesh, flow, pa   (steps listed by GET …/templates)
Flow:
  POST /api/v1/plugins/calibration_runner                       {"template": "full"}
  GET  /api/v1/plugins/calibration_runner[/<id>]
  POST /api/v1/plugins/calibration_runner/<id>/steps/<key>/complete
        {"confirmed": true, "result": {...}}        # result required for measure_* steps
  POST /api/v1/plugins/calibration_runner/<id>/steps/<key>/skip

Results:  measure_flow {"measured_mm": 0.44, "expected_mm": 0.42}
            -> M221 percentage (expected / measured × 100, limited to 85-115 %)
          measure_pa   {"best_pa": 0.045}   (0 - 2)
            -> pressure_advance line for printer.cfg
"""

import time

from plugins._common import data_dir, read_json, write_json

PLUGIN_INFO = {
    "title": "Calibration workflow",
    "description": "Ordered, reviewable calibration checklist with result validation and recommendations. Executes nothing.",
}

STEPS = {
    "home": {"title": "Home all axes", "kind": "auto", "endpoint": "POST /api/v1/calibration/run",
             "body": {"step": "home", "confirmed": True}},
    "pid_hotend": {"title": "PID tune the hotend", "kind": "auto", "endpoint": "POST /api/v1/calibration/run",
                   "body": {"step": "pid_hotend", "target": 200, "confirmed": True}},
    "pid_bed": {"title": "PID tune the bed", "kind": "auto", "endpoint": "POST /api/v1/calibration/run",
                "body": {"step": "pid_bed", "target": 60, "confirmed": True}},
    "bed_mesh": {"title": "Bed mesh", "kind": "auto", "endpoint": "POST /api/v1/calibration/run",
                 "body": {"step": "bed_mesh", "confirmed": True}},
    "save": {"title": "SAVE_CONFIG (restarts Klipper)", "kind": "auto", "endpoint": "POST /api/v1/calibration/run",
             "body": {"step": "save", "confirmed": True}},
    "flow_sample": {"title": "Upload the flow sample, print it, measure the wall", "kind": "auto",
                    "endpoint": "POST /api/v1/calibration/flow-sample", "body": {}},
    "measure_flow": {"title": "Enter the measured wall thickness", "kind": "manual"},
    "pa_test": {"title": "Upload the pressure-advance pattern and print it", "kind": "auto",
                "endpoint": "POST /api/v1/calibration/pa-test", "body": {"pa_start": 0.0, "pa_end": 0.1, "pa_step": 0.005}},
    "measure_pa": {"title": "Enter the line with the cleanest transitions", "kind": "manual"},
    "shaper": {"title": "Input-shaper resonance test", "kind": "auto",
               "endpoint": "POST /api/v1/twin/shaper/calibrate", "body": {}},
}
TEMPLATES = {
    "full": ["home", "pid_hotend", "pid_bed", "bed_mesh", "save", "flow_sample", "measure_flow",
             "pa_test", "measure_pa", "shaper"],
    "pid": ["home", "pid_hotend", "pid_bed", "save"],
    "mesh": ["home", "bed_mesh", "save"],
    "flow": ["flow_sample", "measure_flow"],
    "pa": ["pa_test", "measure_pa"],
}


class WorkflowError(ValueError):
    pass


def validate_result(key, result):
    result = result or {}
    if key == "measure_flow":
        try:
            measured = float(result["measured_mm"])
            expected = float(result.get("expected_mm", 0.42))
        except (KeyError, TypeError, ValueError):
            raise WorkflowError("measure_flow needs numeric 'measured_mm' (and optional 'expected_mm')")
        if not (0.1 <= measured <= 2.0 and 0.1 <= expected <= 2.0):
            raise WorkflowError("wall thickness values must be between 0.1 and 2.0 mm")
        return {"measured_mm": measured, "expected_mm": expected}
    if key == "measure_pa":
        try:
            pa = float(result["best_pa"])
        except (KeyError, TypeError, ValueError):
            raise WorkflowError("measure_pa needs a numeric 'best_pa'")
        if not 0.0 <= pa <= 2.0:
            raise WorkflowError("best_pa must be between 0 and 2")
        return {"best_pa": pa}
    return result if isinstance(result, dict) else {}


def recommendations(steps):
    out = []
    for s in steps:
        if s["status"] != "done":
            continue
        r = s.get("result") or {}
        if s["key"] == "measure_flow":
            pct = r["expected_mm"] / r["measured_mm"] * 100.0
            clamped = max(85.0, min(115.0, pct))
            out.append({"step": "measure_flow", "flow_percent": round(clamped, 1),
                        "text": f"Measured {r['measured_mm']} mm vs expected {r['expected_mm']} mm → set the slicer flow "
                                f"ratio to about {clamped:.1f} % of its current value"
                                + (" (capped: the raw value was outside 85-115 %, check E-steps first)"
                                   if clamped != pct else "")})
        if s["key"] == "measure_pa":
            out.append({"step": "measure_pa", "pressure_advance": r["best_pa"],
                        "text": f"Add to the [extruder] section of printer.cfg:  pressure_advance: {r['best_pa']}"})
    return out


class Workflows:
    def __init__(self, path=None):
        self._path = path

    def _file(self):
        return self._path or (data_dir() / "calibration_workflows.json")

    def _all(self):
        return read_json(self._file(), {})

    def _save(self, d):
        write_json(self._file(), d)

    def create(self, template, now=None):
        if template not in TEMPLATES:
            raise WorkflowError(f"unknown template '{template}' (known: {', '.join(TEMPLATES)})")
        d = self._all()
        wid = str(int(max([int(k) for k in d] + [int(time.time())]) + 1))
        d[wid] = {"id": wid, "template": template, "created": now or time.time(),
                  "steps": [{"key": k, **{f: v for f, v in STEPS[k].items()}, "status": "pending",
                             "result": None, "completed": None} for k in TEMPLATES[template]]}
        self._save(d)
        return self.view(d[wid])

    @staticmethod
    def view(w):
        nxt = next((s["key"] for s in w["steps"] if s["status"] == "pending"), None)
        return {**w, "next_step": nxt, "finished": nxt is None, "recommendations": recommendations(w["steps"])}

    def get(self, wid):
        w = self._all().get(wid)
        return self.view(w) if w else None

    def list(self):
        return [self.view(w) for w in self._all().values()]

    def step(self, wid, key, action, confirmed=False, result=None, now=None):
        d = self._all()
        w = d.get(wid)
        if not w:
            raise KeyError("workflow not found")
        step = next((s for s in w["steps"] if s["key"] == key), None)
        if step is None:
            raise KeyError("step not in this workflow")
        if step["status"] != "pending":
            raise WorkflowError(f"step already {step['status']}")
        pending = [s["key"] for s in w["steps"] if s["status"] == "pending"]
        if pending[0] != key:
            raise WorkflowError(f"complete or skip '{pending[0]}' first (steps run in order)")
        if action == "complete":
            if confirmed is not True:
                raise WorkflowError("explicit confirmation is required: send {'confirmed': true}")
            step["result"] = validate_result(key, result) if step["kind"] == "manual" else (result or None)
            step["status"] = "done"
        else:
            step["status"] = "skipped"
        step["completed"] = now or time.time()
        self._save(d)
        return self.view(w)


workflows = Workflows()


def register_routes(app) -> None:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("plugin_calibration_runner", __name__, url_prefix="/api/v1/plugins/calibration_runner")

    @bp.route("", methods=["GET"])
    def listing():
        return jsonify({"templates": {k: v for k, v in TEMPLATES.items()}, "workflows": workflows.list()})

    @bp.route("", methods=["POST"])
    def create():
        try:
            return jsonify(workflows.create((request.get_json(force=True, silent=True) or {}).get("template", "full"))), 201
        except WorkflowError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/<wid>", methods=["GET"])
    def one(wid):
        w = workflows.get(wid)
        return (jsonify(w), 200) if w else (jsonify({"error": "workflow not found"}), 404)

    def _step(wid, key, action):
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(workflows.step(wid, key, action, body.get("confirmed"), body.get("result")))
        except KeyError as e:
            return jsonify({"error": str(e.args[0])}), 404
        except WorkflowError as e:
            return jsonify({"error": str(e)}), 409 if "first" in str(e) or "already" in str(e) else 400

    @bp.route("/<wid>/steps/<key>/complete", methods=["POST"])
    def complete(wid, key):
        return _step(wid, key, "complete")

    @bp.route("/<wid>/steps/<key>/skip", methods=["POST"])
    def skip(wid, key):
        return _step(wid, key, "skip")

    app.register_blueprint(bp)
