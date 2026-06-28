import json
import time
import requests as req
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sock import Sock

from api.routes.control import control_bp
from api.routes.telemetry import telemetry_bp
from api.routes.twin import twin_bp
from api.routes.profile import profile_bp
from api.routes.sim import sim_bp

app  = Flask(__name__)
sock = Sock(app)
CORS(app)

app.register_blueprint(control_bp,   url_prefix="/api/control")
app.register_blueprint(telemetry_bp, url_prefix="/api")
app.register_blueprint(twin_bp,      url_prefix="/api/twin")
app.register_blueprint(profile_bp,   url_prefix="/api/profile")
app.register_blueprint(sim_bp,       url_prefix="/api/sim")


def _worker():
    import workers
    return workers._active_worker


# ── WebSocket ─────────────────────────────────────────────────────────────────
@sock.route("/ws/twin")
def ws_twin(ws):
    print("🔌 WS client connected")
    try:
        while True:
            w = _worker()
            if w and w.latest:
                ws.send(json.dumps(w.latest))
            time.sleep(0.1)
    except Exception:
        print("🔌 WS client disconnected")


# ── Control ───────────────────────────────────────────────────────────────────
@app.route("/api/control/execute", methods=["POST"])
def execute():
    data  = request.json or {}
    gcode = data.get("command", "").strip()
    if not gcode:
        return jsonify({"error": "No command"}), 400
    w = _worker()
    if w and hasattr(w, "inject_gcode"):
        w.inject_gcode(gcode)
        return jsonify({"status": "queued", "command": gcode})
    from api.routes.control import get_queue
    q = get_queue()
    if q is None:
        return jsonify({"error": "Queue not initialized"}), 500
    try:
        cmd = q.create_command(gcode=gcode, source="frontend", priority=1)
        q.enqueue(cmd)
        return jsonify({"status": "queued", "command": gcode})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── File upload + print start ─────────────────────────────────────────────────
@app.route("/api/print/upload", methods=["POST"])
def upload_and_print():
    """
    Accepts a .gcode file upload, forwards it to Moonraker,
    and optionally starts printing immediately.
    Body: multipart/form-data with 'file' field.
    Query param: ?start=1 to start printing after upload.
    """
    from config.loader import get_moonraker_url
    moonraker = get_moonraker_url()

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f         = request.files["file"]
    start_now = request.args.get("start", "0") == "1"

    # Forward to Moonraker file upload endpoint
    try:
        files_payload = {"file": (f.filename, f.stream, "application/octet-stream")}
        data_payload  = {"root": "gcodes"}
        if start_now:
            data_payload["print"] = "true"

        res = req.post(
            f"{moonraker}/server/files/upload",
            files=files_payload,
            data=data_payload,
            timeout=30,
        )
        if res.ok:
            return jsonify({"status": "ok", "filename": f.filename, "started": start_now})
        return jsonify({"error": f"Moonraker upload failed: {res.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/print/start", methods=["POST"])
def start_print():
    """Start printing a file already on Moonraker."""
    from config.loader import get_moonraker_url
    moonraker = get_moonraker_url()
    data      = request.json or {}
    filename  = data.get("filename", "")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        res = req.post(
            f"{moonraker}/printer/print/start",
            json={"filename": filename},
            timeout=5,
        )
        return jsonify({"status": "ok" if res.ok else "error", "code": res.status_code})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/print/pause",  methods=["POST"])
def pause_print():
    from config.loader import get_moonraker_url
    try:
        req.post(f"{get_moonraker_url()}/printer/print/pause", timeout=3)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/print/resume", methods=["POST"])
def resume_print():
    from config.loader import get_moonraker_url
    try:
        req.post(f"{get_moonraker_url()}/printer/print/resume", timeout=3)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/print/cancel", methods=["POST"])
def cancel_print():
    from config.loader import get_moonraker_url
    try:
        req.post(f"{get_moonraker_url()}/printer/print/cancel", timeout=3)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Telemetry (legacy HTTP) ───────────────────────────────────────────────────
@app.route("/api/telemetry", methods=["GET"])
def get_telemetry():
    w = _worker()
    d = w.latest if w else {}
    if not d:
        return jsonify({"x": 0, "y": 0, "z": 0, "extTemp": 0, "bedTemp": 0, "state": "offline"})
    return jsonify({
        "x":             d.get("cmd_x", 0),
        "y":             d.get("cmd_y", 0),
        "z":             d.get("cmd_z", 0),
        "extTemp":       d.get("ext_temp", 0),
        "bedTemp":       d.get("bed_temp", 0),
        "state":         d.get("print_state", "unknown"),
        "filename":      d.get("filename", ""),
        "file_position": d.get("file_position", 0),
        "progress":      d.get("progress", 0),
        "time_remaining": d.get("time_remaining", 0),
        "print_duration": d.get("print_duration", 0),
        "speed_factor":  d.get("speed_factor", 100),
        "flow_factor":   d.get("flow_factor", 100),
    })


@app.route("/api/history", methods=["GET"])
def history():
    w = _worker()
    if w and hasattr(w, "print_history") and w.print_history:
        return jsonify(w.print_history[-20:])
    try:
        from db.models import get_connection
        conn = get_connection()
        c    = conn.cursor()
        c.execute("SELECT filename, status, timestamp FROM print_history ORDER BY id DESC LIMIT 20")
        rows = [{"filename": r[0], "status": r[1], "timestamp": r[2]} for r in c.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception:
        return jsonify([])


@app.route("/api/environment", methods=["GET"])
def environment():
    w = _worker()
    # Sim worker has real simulated environment
    if w and hasattr(w, "environment"):
        return jsonify(w.environment)
    # Live mode — return zeros until real BME280 sensor is wired
    # Do NOT fall back to ext_temp (causes 209°C ambient reading)
    return jsonify({"temperature": 0.0, "humidity": 0.0})


@app.route("/api/power", methods=["GET"])
def power():
    w = _worker()
    if w and hasattr(w, "power"):
        return jsonify(w.power)
    return jsonify({"voltage": 0.0, "current": 0.0, "power": 0.0})


@app.route("/api/maintenance", methods=["GET"])
def maintenance():
    w = _worker()
    if w and hasattr(w, "maintenance_hints"):
        return jsonify({"hints": w.maintenance_hints})
    return jsonify({"hints": []})


def run_server():
    print("🌐 API Server running on http://0.0.0.0:5001")
    app.run(host="0.0.0.0", port=5001)
