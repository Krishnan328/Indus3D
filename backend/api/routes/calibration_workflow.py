"""API for a guarded, analysis-first calibration workflow."""

from flask import Blueprint, jsonify, request

from db.models import get_connection
from services.calibration_workflow import (PHASES, approve_persistence, create_workflow, get_workflow,
                                           plan_command, record_collection, record_validation)

calibration_workflow_bp = Blueprint("calibration_workflow", __name__)


def _readiness():
    import workers
    worker = workers._active_worker
    if worker is None:
        return {"ready": False, "reason": "Indus3D telemetry worker is unavailable"}
    simulated = hasattr(worker, "shape")
    latest = getattr(worker, "latest", {}) if isinstance(getattr(worker, "latest", {}), dict) else {}
    state = latest.get("print_state", getattr(worker, "state", "standby"))
    klippy_state = latest.get("klippy_state", getattr(worker, "_klippy_state", "unknown"))
    connected = latest.get("klippy_connected", getattr(worker, "_klippy_connected", False))
    if simulated:
        return {"ready": True, "simulated": True, "print_state": state, "klippy_state": klippy_state}
    if klippy_state != "ready" or not connected:
        return {"ready": False, "reason": f"Klipper is {klippy_state or 'unavailable'}", "print_state": state, "klippy_state": klippy_state}
    if state in ("printing", "paused"):
        return {"ready": False, "reason": "An active or paused job blocks calibration", "print_state": state, "klippy_state": klippy_state}
    return {"ready": True, "simulated": False, "print_state": state, "klippy_state": klippy_state}


def _rollback_snapshot():
    from config.loader import get_profile
    return {"captured_at": __import__("time").time(), "profile": get_profile(),
            "scope": "Indus3D profile snapshot for manual comparison; it does not replace a printer.cfg backup."}


def _error(error, status=400):
    return jsonify({"error": str(error)}), status


@calibration_workflow_bp.route("/status", methods=["GET"])
def workflow_status():
    return jsonify({"readiness": _readiness(), "phases": PHASES,
                    "automation": "collection_and_analysis_only",
                    "safety_note": "This workflow generates review plans; it does not execute or persist printer commands."})


@calibration_workflow_bp.route("/sessions", methods=["POST"])
def start_workflow():
    conn = get_connection()
    try:
        payload = request.get_json(silent=True) or {}
        workflow = create_workflow(conn, payload.get("preflight"), _readiness(), _rollback_snapshot())
        return jsonify({"workflow": workflow}), 201
    except RuntimeError as error:
        return _error(error, 409)
    except ValueError as error:
        return _error(error)
    finally:
        conn.close()


@calibration_workflow_bp.route("/sessions/<workflow_id>", methods=["GET"])
def workflow_detail(workflow_id):
    conn = get_connection()
    try:
        workflow = get_workflow(conn, workflow_id)
        return jsonify({"workflow": workflow}) if workflow else _error("Calibration workflow was not found", 404)
    finally:
        conn.close()


@calibration_workflow_bp.route("/sessions/<workflow_id>/collect", methods=["POST"])
def collect(workflow_id):
    import workers
    worker = workers._active_worker
    snapshot = getattr(worker, "latest", {}) if worker else {}
    conn = get_connection()
    try:
        return jsonify({"workflow": record_collection(conn, workflow_id, snapshot if isinstance(snapshot, dict) else {}, _readiness())})
    except LookupError as error:
        return _error(error, 404)
    except RuntimeError as error:
        return _error(error, 409)
    finally:
        conn.close()


@calibration_workflow_bp.route("/sessions/<workflow_id>/command-plan", methods=["POST"])
def command_plan(workflow_id):
    payload = request.get_json(silent=True) or {}
    conn = get_connection()
    try:
        return jsonify({"plan": plan_command(conn, workflow_id, payload.get("phase"), payload, _readiness())})
    except LookupError as error:
        return _error(error, 404)
    except (RuntimeError, ValueError) as error:
        return _error(error, 409 if isinstance(error, RuntimeError) else 400)
    finally:
        conn.close()


@calibration_workflow_bp.route("/sessions/<workflow_id>/validation", methods=["POST"])
def validation(workflow_id):
    conn = get_connection()
    try:
        return jsonify({"workflow": record_validation(conn, workflow_id, request.get_json(silent=True) or {}, _readiness())})
    except LookupError as error:
        return _error(error, 404)
    except (RuntimeError, ValueError) as error:
        return _error(error, 409 if isinstance(error, RuntimeError) else 400)
    finally:
        conn.close()


@calibration_workflow_bp.route("/sessions/<workflow_id>/persistence-approval", methods=["POST"])
def persistence_approval(workflow_id):
    conn = get_connection()
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify({"workflow": approve_persistence(conn, workflow_id, payload.get("operator"))})
    except LookupError as error:
        return _error(error, 404)
    except (RuntimeError, ValueError) as error:
        return _error(error, 409 if isinstance(error, RuntimeError) else 400)
    finally:
        conn.close()
