from flask import Blueprint, jsonify, request
from digital_twin.kinematic_model import kinematic_model
from digital_twin.snapshot_logger import get_recent_snapshots
from core.alert_actions import execute_alert_action, get_action_log, clear_all_actioned

twin_bp = Blueprint("twin", __name__)


def _latest():
    import workers
    w = workers._active_worker
    return w.latest if w else {}


@twin_bp.route("/state", methods=["GET"])
def twin_state():
    return jsonify(_latest())


@twin_bp.route("/kinematics", methods=["GET"])
def kinematics():
    d = _latest()
    return jsonify({
        "kinematics": d.get("kinematics", {}),
        "cmd_pos":    {"x": d.get("cmd_x", 0), "y": d.get("cmd_y", 0),
                       "z": d.get("cmd_z", 0), "e": d.get("cmd_e", 0)},
        "live_pos":   {"x": d.get("live_x", 0), "y": d.get("live_y", 0),
                       "z": d.get("live_z", 0)},
        "velocity":   d.get("velocity", 0),
    })


@twin_bp.route("/thermals", methods=["GET"])
def thermals():
    d = _latest()
    return jsonify({
        "thermals":   d.get("thermals", {}),
        "ext_temp":   d.get("ext_temp", 0),
        "ext_target": d.get("ext_target", 0),
        "bed_temp":   d.get("bed_temp", 0),
        "bed_target": d.get("bed_target", 0),
    })


@twin_bp.route("/extrusion", methods=["GET"])
def extrusion():
    return jsonify(_latest().get("extrusion", {}))


@twin_bp.route("/odometry", methods=["GET"])
def odometry():
    return jsonify(kinematic_model.get_lifetime_odometry())


@twin_bp.route("/snapshots", methods=["GET"])
def snapshots():
    limit = int(request.args.get("limit", 200))
    return jsonify(get_recent_snapshots(limit))


# ── Alert action endpoints ────────────────────────────────────────────────────

@twin_bp.route("/action/execute", methods=["POST"])
def action_execute():
    """
    Manually trigger a corrective action for an alert.
    Body: { "alert_id": "lag" }
    """
    data       = request.json or {}
    alert_id   = data.get("alert_id", "")
    d          = _latest()
    print_state = d.get("print_state", "standby")

    if not alert_id:
        return jsonify({"error": "alert_id required"}), 400

    result = execute_alert_action(alert_id, print_state)
    return jsonify(result)


@twin_bp.route("/action/log", methods=["GET"])
def action_log():
    """Return the history of automated actions taken."""
    limit = int(request.args.get("limit", 50))
    return jsonify(get_action_log(limit))


@twin_bp.route("/action/reset", methods=["POST"])
def action_reset():
    """Reset the alert deduplication set (call at print start)."""
    clear_all_actioned()
    return jsonify({"status": "ok"})
