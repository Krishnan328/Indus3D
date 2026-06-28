from flask import Blueprint, request, jsonify

control_bp = Blueprint("control", __name__)
_cmd_queue = None


def set_queue(q):
    global _cmd_queue
    _cmd_queue = q


def get_queue():
    return _cmd_queue


@control_bp.route("/execute", methods=["POST"])
def execute_command():
    # Overridden by server.py's direct /api/control/execute route.
    # Kept for blueprint registration compatibility.
    if _cmd_queue is None:
        return jsonify({"error": "Queue not initialized"}), 500
    data  = request.json or {}
    gcode = data.get("command", "")
    if not gcode:
        return jsonify({"error": "No command provided"}), 400
    try:
        cmd = _cmd_queue.create_command(gcode=gcode, source="frontend", priority=1)
        _cmd_queue.enqueue(cmd)
        return jsonify({"status": "queued", "command": gcode})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
