"""Passive experiment history API for the Printer Lab dashboard."""

from flask import Blueprint, jsonify, request

from db.models import get_connection
from services.lab_runs import (DEFAULT_BUDGETS, budget_evaluation, compare_measurements,
                               create_baseline, create_run, fetch_baselines, fetch_runs,
                               get_run, update_run)
from services.prediction_analysis import analyze, validate_predictions

lab_bp = Blueprint("lab", __name__)


def _error(exc, status=400):
    return jsonify({"error": str(exc)}), status


@lab_bp.route("/runs", methods=["GET"])
def list_runs():
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)
    except ValueError:
        return _error("limit must be an integer")
    conn = get_connection()
    try:
        return jsonify({"runs": fetch_runs(conn, limit)})
    finally:
        conn.close()


@lab_bp.route("/runs", methods=["POST"])
def add_run():
    conn = get_connection()
    try:
        run = create_run(conn, request.get_json(silent=True) or {})
        return jsonify({"run": run}), 201
    except ValueError as exc:
        return _error(exc)
    finally:
        conn.close()


@lab_bp.route("/runs/<int:run_id>", methods=["PATCH"])
def edit_run(run_id):
    conn = get_connection()
    try:
        run = update_run(conn, run_id, request.get_json(silent=True) or {})
        if run is None:
            return _error("run not found", 404)
        return jsonify({"run": run})
    except ValueError as exc:
        return _error(exc)
    finally:
        conn.close()


@lab_bp.route("/baselines", methods=["GET"])
def list_baselines():
    conn = get_connection()
    try:
        return jsonify({"baselines": fetch_baselines(conn), "default_budgets": DEFAULT_BUDGETS})
    finally:
        conn.close()


@lab_bp.route("/baselines", methods=["POST"])
def add_baseline():
    payload = request.get_json(silent=True) or {}
    conn = get_connection()
    try:
        baseline = create_baseline(conn, payload.get("name"), payload.get("run_id"), payload.get("budgets"))
        return jsonify({"baseline": baseline}), 201
    except LookupError as exc:
        return _error(exc, 404)
    except ValueError as exc:
        return _error(exc)
    finally:
        conn.close()


@lab_bp.route("/summary", methods=["GET"])
def summary():
    conn = get_connection()
    try:
        runs = fetch_runs(conn, 100)
        baselines = fetch_baselines(conn)
        primary = baselines[0] if baselines else None
        active_budgets = primary["budgets"] if primary else DEFAULT_BUDGETS
        enriched = []
        for run in runs:
            entry = {**run, "budget_evaluation": budget_evaluation(run, active_budgets)}
            if primary and run["id"] != primary["run"]["id"]:
                entry["comparison"] = {"baseline_id": primary["id"],
                                       "baseline_name": primary["name"],
                                       "metrics": compare_measurements(run, primary)}
            enriched.append(entry)
        return jsonify({"runs": enriched, "baselines": baselines, "default_budgets": DEFAULT_BUDGETS,
                        "active_budgets": active_budgets,
                        "passive_only": True})
    finally:
        conn.close()


@lab_bp.route("/analyze", methods=["POST"])
def analyze_prediction_reality():
    """Run a pure, non-persistent comparison for imported or prospective data."""
    payload = request.get_json(silent=True) or {}
    try:
        predictions = validate_predictions(payload.get("predictions"))
        measurements = payload.get("measurements") or {}
        if not isinstance(measurements, dict):
            raise ValueError("measurements must be an object")
        # Creation validation owns the persisted field allowlist; this route is
        # deliberately narrow and only consumes known actual values.
        allowed = {"actual_time_s", "energy_wh", "filament_g", "extruder_temp_c", "bed_temp_c",
                   "path_length_mm", "position_error_mm", "vibration_rms"}
        unknown = set(measurements) - allowed
        if unknown:
            raise ValueError(f"Unknown measurement(s): {', '.join(sorted(unknown))}")
        from services.prediction_analysis import finite_nonnegative
        actual = {key: finite_nonnegative(value, key) for key, value in measurements.items()
                  if value not in (None, "")}
        estimated = payload.get("slicer_estimated_seconds")
        if estimated not in (None, ""):
            estimated = finite_nonnegative(estimated, "slicer_estimated_seconds")
        return jsonify({"analysis": analyze(predictions, actual, estimated)})
    except ValueError as exc:
        return _error(exc)
