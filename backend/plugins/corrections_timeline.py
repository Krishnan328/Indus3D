"""
plugins/corrections_timeline.py  (G1)
---------------------------------------
Chart-ready data: every correction of a print against print progress, per
parameter family. Pure data endpoint for a dashboard widget or Grafana JSON.

GET /api/v1/plugins/corrections_timeline?run=<id|current>&include=applied,shadow,vetoed
"""

PLUGIN_INFO = {
    "title": "Corrections timeline",
    "description": "Corrections vs print progress per family, for charts.",
}


def build(run: dict, include=("applied", "shadow", "vetoed")) -> dict:
    series = {}

    def add(fam, kind, progress, value, command):
        series.setdefault(fam or "other", []).append(
            {"progress": round((progress or 0.0) * 100, 1), "kind": kind, "value": value, "command": command})

    if "applied" in include:
        for c in run.get("commands", []):
            add(c["family"], "applied" if c["ok"] else "failed", c.get("progress"), c.get("value"), c["command"])
    if "shadow" in include:
        for c in run.get("shadow", []):
            add(c["family"], "shadow", c.get("progress"), c.get("value"), c["command"])
    if "vetoed" in include:
        from plugins.arbiter import family_of, s_value
        for v in run.get("vetoes", []):
            add(family_of(v["command"]), "vetoed", None, s_value(v["command"]), v["command"])
    for pts in series.values():
        pts.sort(key=lambda p: p["progress"])
    return {"run": run["id"], "filename": run.get("filename"), "final_state": run.get("final_state"),
            "series": series,
            "reasons": [{"progress": round((c.get("progress") or 0) * 100, 1), "type": c.get("type"),
                         "value": c.get("value"), "reason": c.get("reason")} for c in run.get("corrections", [])]}


def register_routes(app) -> None:
    from flask import Blueprint, jsonify, request
    from plugins.run_recorder import recorder

    bp = Blueprint("plugin_corrections_timeline", __name__, url_prefix="/api/v1/plugins/corrections_timeline")

    @bp.route("", methods=["GET"])
    def timeline():
        raw = request.args.get("run", "current")
        key = "current" if raw == "current" else (int(raw) if raw.isdigit() else None)
        run = recorder.get(key) if key is not None else None
        if run is None and raw == "current" and recorder.history:
            run = recorder.history[0]                      # no live print: show the latest finished one
        if run is None:
            return jsonify({"error": "run not found"}), 404
        include = tuple(x for x in request.args.get("include", "applied,shadow,vetoed").split(",") if x)
        return jsonify(build(run, include))

    app.register_blueprint(bp)
