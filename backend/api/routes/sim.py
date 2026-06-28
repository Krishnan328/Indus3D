"""
api/routes/sim.py
------------------
Exposes simulator-specific data to the frontend.
Key addition: /api/sim/gcode_file — serves the synthetic G-code
so the GCodeVisualizer can parse and render it exactly like a real file.
"""

from flask import Blueprint, jsonify, Response, request

sim_bp = Blueprint("sim", __name__)


def _worker():
    import workers
    return workers._active_worker


@sim_bp.route("/power", methods=["GET"])
def power():
    w = _worker()
    if w and hasattr(w, "power"):
        return jsonify(w.power)
    return jsonify({"voltage": 0, "current": 0, "power": 0})


@sim_bp.route("/environment", methods=["GET"])
def environment():
    w = _worker()
    if w and hasattr(w, "environment"):
        return jsonify(w.environment)
    return jsonify({"temperature": 0, "humidity": 0})


@sim_bp.route("/gcode_feed", methods=["GET"])
def gcode_feed():
    w = _worker()
    if w and hasattr(w, "gcode_feed"):
        return jsonify(list(w.gcode_feed))
    return jsonify([])


@sim_bp.route("/maintenance", methods=["GET"])
def maintenance():
    w = _worker()
    if w and hasattr(w, "maintenance_hints"):
        return jsonify({"hints": w.maintenance_hints})
    return jsonify({"hints": []})


@sim_bp.route("/history", methods=["GET"])
def sim_history():
    w = _worker()
    if w and hasattr(w, "print_history"):
        return jsonify(w.print_history[-20:])
    try:
        from db.models import get_connection
        conn = get_connection(); c = conn.cursor()
        c.execute("SELECT filename, status, timestamp FROM print_history ORDER BY id DESC LIMIT 20")
        rows = [{"filename": r[0], "status": r[1], "timestamp": r[2]} for r in c.fetchall()]
        conn.close(); return jsonify(rows)
    except:
        return jsonify([])


@sim_bp.route("/gcode_file", methods=["GET"])
def gcode_file():
    """
    Serve the synthetic G-code for the current sim shape.
    The GCodeVisualizer fetches this in sim mode instead of
    hitting Moonraker's /server/files/gcodes/<filename>.

    Query params:
        ?shape=benchy|cube   (default: whatever the sim was started with)
        ?layers=N            (default: 40)
    """
    w = _worker()

    # If simulator is running and already has G-code built, serve it
    if w and hasattr(w, "gcode_str") and w.gcode_str:
        return Response(
            w.gcode_str,
            mimetype="text/plain",
            headers={
                "Content-Type":  "text/plain; charset=utf-8",
                "Cache-Control": "no-cache",
            }
        )

    # Otherwise build on-demand from query params
    shape  = request.args.get("shape",  "benchy")
    layers = int(request.args.get("layers", "40"))

    try:
        from workers.gcode_shapes import get_shape_gcode
        gcode_str, _ = get_shape_gcode(shape, layers)
        return Response(gcode_str, mimetype="text/plain")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sim_bp.route("/info", methods=["GET"])
def sim_info():
    """Returns current sim shape and layer count for the frontend to display."""
    w = _worker()
    if w and hasattr(w, "shape"):
        return jsonify({
            "shape":     w.shape,
            "mode":      "sim",
            "waypoints": len(w._waypoints) if hasattr(w, "_waypoints") else 0,
            "wp_idx":    w._wp_idx if hasattr(w, "_wp_idx") else 0,
        })
    return jsonify({"shape": "unknown", "mode": "live"})
