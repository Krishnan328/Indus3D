import core.logger

"""
api/server.py
--------------
Flask application factory.
All Moonraker access is proxied through /api/printer/* — the frontend
never calls port 7125 directly.
"""

import logging
import json
import os
import socket
import time
from io import BytesIO
import requests as req
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from flasgger import Swagger
from flask_sock import Sock

from config.settings import settings
from api.routes.twin import twin_bp
from api.routes.edge import edge_bp
from api.routes.profile import profile_bp
from api.routes.spools import spools_bp
from api.routes.sim import sim_bp
from api.routes.printer import printer_bp
from api.routes.bed import bed_bp
from api.auth import auth_bp, install_auth_gate, get_or_create_secret_key, auth_required

app  = Flask(__name__)
sock = Sock(app)

# CORS — supports_credentials=True is required for session cookies to work
# cross-origin (frontend dev server on :5173, backend on :5001). When auth
# is enabled, the frontend sends credentials:'include' on every fetch;
# CORS with credentials rejects wildcard origins, so we reflect the request
# origin. This is not the security boundary — the password is.
_cors_origins = settings.CORS_ORIGINS if settings.CORS_ORIGINS != "*" else r".*"
CORS(app, supports_credentials=True, origins=_cors_origins)


# Initialize Swagger API Documentation
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/api/v1/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/docs/"
}
Swagger(app, config=swagger_config, template={"info": {"title": "Indus3D API", "version": "1.0", "description": "API for Indus3D Digital Twin."}})


# NOTE: there is no separate "/api/control" blueprint. The old cmd_queue /
# QueueWorker / control_bp pipeline (priority-queued G-code execution) was
# never actually reachable — every request landed on the /api/control/execute
# route defined directly below instead, which talks to the sim injector or
# Moonraker immediately. That whole subsystem has been removed; this route
# is the one and only implementation now.
app.register_blueprint(twin_bp,     url_prefix="/api/v1/twin")
app.register_blueprint(edge_bp,     url_prefix="/api/v1/edge")
app.register_blueprint(profile_bp,  url_prefix="/api/v1/profile")
app.register_blueprint(sim_bp,      url_prefix="/api/v1/sim")
app.register_blueprint(spools_bp,   url_prefix="/api/v1/spools")
app.register_blueprint(printer_bp,  url_prefix="/api/v1/printer")
app.register_blueprint(bed_bp,      url_prefix="/api/v1/bed")
app.register_blueprint(auth_bp)

# Session secret + auth gate
app.secret_key = get_or_create_secret_key()
install_auth_gate(app)
from api.rate_limiter import check_rate_limit
check_rate_limit(app)

# Startup auth message

@app.after_request
def add_deprecation_headers(response):
    # We can tag paths with "v1" as deprecated in the future
    # if request.path.startswith("/api/v0/"):
    #     response.headers["Deprecation"] = "true"
    #     response.headers["Link"] = '<http://localhost:5001/api/v1/>; rel="successor-version"'
    return response


if auth_required():
    logging.info("🔒 Authentication enabled — all routes require login")
else:
    logging.info("🔓 No INDUS3D_PASSWORD set — running without authentication")
    logging.info("   (set INDUS3D_PASSWORD in backend/.env to enable login)")

# /api/config lives on printer_bp but needs a top-level alias too
@app.route("/api/v1/config", methods=["GET"])
def api_config():
    return jsonify({
        "moonraker_url":     settings.moonraker_url,
        "webcam_stream_url": settings.webcam_stream_url,
        "flask_port":        settings.FLASK_PORT,
    })


def _worker():
    import workers
    return workers._active_worker


def _printer_is_busy(worker) -> bool:
    """Manual motion and calibration must never interleave with a print."""
    state = (worker.latest if worker else {}).get("print_state", "standby")
    return state in ("printing", "paused")


def _run_managed_gcode(script: str):
    """Run a backend-owned command sequence and mirror it in the terminal.

    This is deliberately separate from the free-form terminal route: callers
    only reach it through fixed, validated jog and calibration actions below.
    """
    w = _worker()
    if w and hasattr(w, "inject_gcode"):
        w.inject_gcode(script)
        return {"status": "queued", "simulated": True}

    res = req.post(
        f"{settings.moonraker_url}/printer/gcode/script",
        params={"script": script}, timeout=10,
    )
    if not res.ok:
        return {"status": "error", "detail": res.text[:300]}
    if w and hasattr(w, "live_commands"):
        for line in script.splitlines():
            if line.strip():
                w.live_commands.append({"text": f"[INDUS] {line}", "ts": time.time()})
    return {"status": "ok", "simulated": False}


# ── WebSocket — 10 Hz push ────────────────────────────────────────────────────
@sock.route("/api/v1/ws/twin")
def ws_twin(ws):
    logging.info("🔌 WS client connected")
    try:
        while True:
            w = _worker()
            if w and w.latest:
                sim_state = w.latest.copy()
                if "kinematics" in sim_state:
                    sim_state.update(sim_state.pop("kinematics"))
                if "thermals" in sim_state:
                    sim_state.update(sim_state.pop("thermals"))
                if "extrusion" in sim_state:
                    sim_state.update(sim_state.pop("extrusion"))
                ws.send(json.dumps(sim_state))
            time.sleep(0.1)
    except Exception:
        logging.info("🔌 WS client disconnected")


# ── Control execute ───────────────────────────────────────────────────────────
@app.route("/api/v1/control/execute", methods=["POST"])
def execute():
    data  = request.json or {}
    gcode = data.get("command", "").strip()
    if not gcode:
        return jsonify({"error": "No command"}), 400

    w = _worker()

    # Sim mode — inject into simulator
    if w and hasattr(w, "inject_gcode"):
        w.inject_gcode(gcode)
        return jsonify({"status": "queued", "command": gcode})

    # Live mode — forward to Moonraker via proxy
    from api.routes.printer import _is_safe_gcode
    if not _is_safe_gcode(gcode):
        return jsonify({"error": f"Command not in safe list: {gcode}"}), 403
    try:
        res = req.post(
            f"{settings.moonraker_url}/printer/gcode/script",
            params={"script": gcode},
            timeout=5,
        )
        # Also add to live_commands feed so terminal shows it
        if w and hasattr(w, "live_commands"):
            w.live_commands.append({"text": gcode, "ts": time.time()})
        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ── Guided machine controls ───────────────────────────────────────────────────
@app.route("/api/v1/control/home", methods=["POST"])
def home_axes():
    w = _worker()
    if _printer_is_busy(w):
        return jsonify({"error": "Cannot home while a print is active"}), 409
    try:
        if w and hasattr(w, "home"):
            w.home()
            return jsonify({"status": "queued", "simulated": True})
        return jsonify(_run_managed_gcode("G28"))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/v1/control/jog", methods=["POST"])
def jog_toolhead():
    """Bounded relative motion for the Mainsail-style toolhead panel."""
    w = _worker()
    if _printer_is_busy(w):
        return jsonify({"error": "Jogging is disabled while a print is active"}), 409
    data = request.get_json(force=True, silent=True) or {}
    try:
        delta = {axis: float(data.get(axis, 0)) for axis in ("x", "y", "z", "e")}
        feedrate = float(data.get("feedrate", 3000))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid jog values"}), 400
    if not any(delta.values()) or any(abs(value) > 100 for value in delta.values()):
        return jsonify({"error": "Each jog must be non-zero and within ±100 mm"}), 400
    if not 60 <= feedrate <= 12000:
        return jsonify({"error": "Feedrate must be between 60 and 12000 mm/min"}), 400
    try:
        if w and hasattr(w, "jog"):
            allowed = w.jog(**delta)
            if allowed is False:
                return jsonify({"error": "Jog blocked by bed safety (exclusion zone or out-of-bounds)"}), 409
            return jsonify({"status": "queued", "simulated": True})
        terms = " ".join(f"{axis.upper()}{value:.3f}" for axis, value in delta.items() if value)
        result = _run_managed_gcode(f"G91\nG1 {terms} F{feedrate:.0f}\nG90")
        return jsonify(result), (200 if result["status"] != "error" else 502)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


def _flow_sample_gcode() -> str:
    """A single-wall 20 mm square for a measured slicer-flow calibration."""
    side, layer_h, line_w = 20.0, 0.2, 0.42
    filament_area = 3.14159265 * (1.75 / 2) ** 2
    e_per_mm = (line_w * layer_h) / filament_area
    e = 0.0
    lines = [
        "; Indus3D flow calibration sample — measure wall thickness after printing",
        "G90", "M82", "G28", "G1 Z5 F1800", "G1 X100 Y100 F6000", "G92 E0",
    ]
    for z in (0.2, 0.4, 0.6):
        lines.append(f"G1 Z{z:.2f} F900")
        for x, y in ((120, 100), (120, 120), (100, 120), (100, 100)):
            e += side * e_per_mm
            lines.append(f"G1 X{x:.2f} Y{y:.2f} E{e:.4f} F1200")
    lines += ["G1 Z10 F1800", "M104 S0", "; END INDUS3D FLOW SAMPLE"]
    return "\n".join(lines) + "\n"




def _pa_test_gcode(pa_start=0.0, pa_end=0.1, pa_step=0.005, hotend_temp=200, bed_temp=60) -> str:
    """
    Generate a Klipper Pressure Advance test pattern.
    
    Prints a series of lines, each at a different PA value.
    Each line has three segments: slow → fast → slow, so the PA effect
    is visible at the speed transitions (bulging = too high, gaps = too low).
    The user picks the K value where transitions are cleanest.
    """
    from config.loader import get_profile
    profile = get_profile()
    bed = profile.get("bed", {})
    bed_x = bed.get("size_x_mm", 220)
    bed_y = bed.get("size_y_mm", 220)

    # Geometry
    line_spacing = 5.0        # mm between lines
    slow_speed = 600          # F value (mm/min) = 10 mm/s
    fast_speed = 6000         # F value (mm/min) = 100 mm/s
    slow_len = 20.0           # mm of slow segment at each end
    fast_len = 40.0           # mm of fast segment in the middle
    total_len = slow_len * 2 + fast_len  # 80 mm
    layer_h = 0.25
    line_w = 0.5
    filament_d = 1.75
    filament_area = 3.14159265 * (filament_d / 2) ** 2
    e_per_mm = (line_w * layer_h) / filament_area

    # Center the pattern on the bed
    x_start = (bed_x - total_len) / 2
    y_start = 30.0  # start near front

    pa_values = []
    v = pa_start
    while v <= pa_end + 1e-9:
        pa_values.append(round(v, 4))
        v += pa_step

    lines = [
        "; ========================================",
        "; Indus3D Pressure Advance Calibration",
        f"; PA range: {pa_start} to {pa_end} step {pa_step}",
        f"; {len(pa_values)} test lines",
        "; Slow-Fast-Slow pattern per line",
        "; Pick the K value where transitions are cleanest",
        "; ========================================",
        "",
        "G90",           # absolute positioning
        "M82",           # absolute extrusion
        f"M140 S{bed_temp}",   # bed temp
        f"M104 S{hotend_temp}", # nozzle temp
        "G28",           # home all
        f"M190 S{bed_temp}",   # wait bed
        f"M109 S{hotend_temp}", # wait nozzle
        "",
        "; Prime line",
        "G92 E0",
        f"G1 X{x_start:.1f} Y10 Z0.3 F3000",
        f"G1 X{x_start + 60:.1f} Y10 E15 F1500",
        "G1 E14 F2400",  # retract slightly
        "G92 E0",
        "",
    ]

    e = 0.0
    for i, pa in enumerate(pa_values):
        y = y_start + i * line_spacing
        if y + line_spacing > bed_y - 10:
            break  # don't go off the bed

        x0 = x_start
        x1 = x_start + slow_len
        x2 = x_start + slow_len + fast_len
        x3 = x_start + total_len

        lines.append(f"; --- PA = {pa:.4f} ---")
        lines.append(f"SET_PRESSURE_ADVANCE ADVANCE={pa:.4f}")
        lines.append(f"G1 X{x0:.2f} Y{y:.2f} Z{layer_h:.2f} F9000")  # travel to start
        
        # Slow segment
        seg_e = slow_len * e_per_mm
        e += seg_e
        lines.append(f"G1 X{x1:.2f} Y{y:.2f} E{e:.4f} F{slow_speed}")
        
        # Fast segment
        seg_e = fast_len * e_per_mm
        e += seg_e
        lines.append(f"G1 X{x2:.2f} Y{y:.2f} E{e:.4f} F{fast_speed}")
        
        # Slow segment
        seg_e = slow_len * e_per_mm
        e += seg_e
        lines.append(f"G1 X{x3:.2f} Y{y:.2f} E{e:.4f} F{slow_speed}")

        # Label — print the K value as a comment the frontend can show
        lines.append(f"M117 PA={pa:.4f}")
        lines.append("")

    lines += [
        "",
        "; Finish",
        "G1 Z10 F1800",
        "G1 X0 Y200 F6000",
        "M104 S0",
        "M140 S0",
        "M84",  # motors off
        "SET_PRESSURE_ADVANCE ADVANCE=0",  # reset PA
        "; END INDUS3D PA CALIBRATION",
    ]
    return "\n".join(lines) + "\n"


@app.route("/api/v1/calibration/status", methods=["GET"])
def calibration_status():
    w = _worker()
    from config.loader import get_profile
    profile = get_profile()
    return jsonify({
        "ready": not _printer_is_busy(w),
        "simulated": bool(w and hasattr(w, "shape")),
        "print_state": (w.latest if w else {}).get("print_state", "offline"),
        "defaults": {"hotend_c": 200, "bed_c": 60, "line_width_mm": profile.get("print", {}).get("line_width_mm", 0.42)},
        "note": "Bed mesh requires a configured probe; flow validation requires a caliper measurement unless a camera/sensor is installed.",
    })


@app.route("/api/v1/calibration/run", methods=["POST"])
def run_calibration_step():
    """Safety-gated Klipper calibration actions; no arbitrary G-code input."""
    w = _worker()
    if _printer_is_busy(w):
        return jsonify({"error": "Calibration cannot run during an active print"}), 409
    data = request.get_json(force=True, silent=True) or {}
    if data.get("confirmed") is not True:
        return jsonify({"error": "Explicit confirmation is required"}), 412
    step = data.get("step", "")
    try:
        if step == "home":
            script = "G28"
        elif step == "bed_mesh":
            script = "G28\nBED_MESH_CALIBRATE"
        elif step in ("pid_hotend", "pid_bed"):
            target = float(data.get("target", 200 if step == "pid_hotend" else 60))
            if step == "pid_hotend" and not 150 <= target <= 300:
                raise ValueError("Hotend PID target must be 150–300 °C")
            if step == "pid_bed" and not 40 <= target <= 120:
                raise ValueError("Bed PID target must be 40–120 °C")
            heater = "extruder" if step == "pid_hotend" else "heater_bed"
            script = f"PID_CALIBRATE HEATER={heater} TARGET={target:.0f}"
        elif step == "save":
            script = "SAVE_CONFIG"
        elif step == "apply_flow":
            flow = float(data.get("flow", 100))
            if not 85 <= flow <= 115:
                raise ValueError("Temporary flow must be 85–115%")
            script = f"M221 S{flow:.0f}"
        else:
            return jsonify({"error": "Unknown calibration step"}), 400
        result = _run_managed_gcode(script)
        return jsonify({**result, "step": step, "command": script}), (200 if result["status"] != "error" else 502)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/v1/calibration/flow-sample", methods=["POST"])
def upload_flow_sample():
    """Upload, but deliberately do not start, the calibration print."""
    w = _worker()
    gcode = _flow_sample_gcode()
    if w and hasattr(w, "shape"):
        return jsonify({"status": "simulation", "filename": "indus_flow_sample.gcode", "gcode": gcode})
    try:
        res = req.post(
            f"{settings.moonraker_url}/server/files/upload",
            files={"file": ("indus_flow_sample.gcode", BytesIO(gcode.encode()), "text/plain")},
            data={"root": "gcodes"}, timeout=30,
        )
        return jsonify({"status": "uploaded" if res.ok else "error", "filename": "indus_flow_sample.gcode"}), (200 if res.ok else 502)
    except Exception as e:
        return jsonify({"error": str(e)}), 502




@app.route("/api/v1/calibration/pa-test", methods=["POST"])
def upload_pa_test():
    """Generate and upload a PA calibration test pattern."""
    w = _worker()
    data = request.get_json(force=True, silent=True) or {}
    pa_start = float(data.get("pa_start", 0.0))
    pa_end = float(data.get("pa_end", 0.1))
    pa_step = float(data.get("pa_step", 0.005))
    hotend_temp = int(data.get("hotend_temp", 200))
    bed_temp = int(data.get("bed_temp", 60))

    if pa_start < 0 or pa_end > 2.0 or pa_step <= 0:
        return jsonify({"error": "Invalid PA range"}), 400

    gcode = _pa_test_gcode(pa_start, pa_end, pa_step, hotend_temp, bed_temp)
    filename = "indus_pa_calibration.gcode"

    if w and hasattr(w, "shape"):
        return jsonify({"status": "simulation", "filename": filename, "gcode": gcode})
    try:
        res = req.post(
            f"{settings.moonraker_url}/server/files/upload",
            files={"file": (filename, BytesIO(gcode.encode()), "text/plain")},
            data={"root": "gcodes"}, timeout=30,
        )
        return jsonify({"status": "uploaded" if res.ok else "error", "filename": filename}), (200 if res.ok else 502)
    except Exception as e:
        return jsonify({"error": str(e)}), 502



@app.route("/api/v1/export/annotated-gcode", methods=["GET"])
def export_annotated_gcode():
    """
    Generate an annotated HTML G-code report for the most recent (or specified) print.
    Query params:
        ?filename=<name>  — specific gcode filename (default: most recent print)
    Returns the HTML directly for download.
    """
    from db.models import get_connection
    from core.alert_actions import get_action_log
    import html as html_mod
    from datetime import datetime

    filename = request.args.get("filename", None)

    # Get the original G-code content
    w = _worker()
    gcode_lines = []

    if w and hasattr(w, "gcode_str") and w.gcode_str:
        # Sim mode — use the simulator's built-in G-code
        gcode_lines = w.gcode_str.split("\n")
        if not filename:
            filename = f"sim_{w.shape}.gcode" if hasattr(w, "shape") else "sim_print.gcode"
    elif filename:
        # Live mode — fetch from Moonraker
        try:
            res = req.get(f"{settings.moonraker_url}/server/files/gcodes/{filename}", timeout=30)
            if res.ok:
                gcode_lines = res.text.split("\n")
        except Exception:
            pass

    if not gcode_lines:
        # Fallback: try to get the currently loaded file
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT filename FROM print_history ORDER BY id DESC LIMIT 1")
            row = c.fetchone()
            conn.close()
            if row:
                filename = row[0]
        except Exception:
            pass
        if not filename:
            filename = "unknown.gcode"
        gcode_lines = ["; No G-code file available — showing action log only"]

    # Get action log
    actions = get_action_log(limit=500)

    # Build merged lines
    merged = []
    for i, line in enumerate(gcode_lines):
        text = line.rstrip("\n").rstrip("\r")
        is_indus = text.strip().startswith("[INDUS]") or text.strip().startswith("[QC]")
        is_user = text.strip().startswith(">>>")
        is_comment = text.strip().startswith(";")
        is_crit = "M112" in text

        if is_crit:
            css, src = "crit", "INDUS3D"
        elif is_indus:
            css, src = "indus", "INDUS3D"
        elif is_user:
            css, src = "user", "User"
        elif is_comment:
            css, src = "comment", "Slicer"
        else:
            css, src = "file", "Slicer"

        merged.append({"ln": i+1, "text": text, "css": css, "src": src})

    # Insert action log entries
    total_file = len(merged)
    actions_sorted = sorted(actions, key=lambda a: a.get("timestamp", 0))
    offset = 0
    for action in actions_sorted:
        if not action.get("gcode"):
            continue
        is_crit = action.get("alert_id", "") in ("ext_runaway", "bed_runaway") or "M112" in (action.get("gcode") or "")
        # Distribute proportionally
        frac = min(1.0, max(0.0, (actions_sorted.index(action)) / max(len(actions_sorted), 1)))
        pos = min(int(frac * total_file) + offset, len(merged))
        desc = action.get("description", "")
        ts_str = ""
        if action.get("timestamp"):
            ts_str = datetime.fromtimestamp(action["timestamp"]).strftime("%H:%M:%S")
        merged.insert(pos, {
            "ln": "►",
            "text": f"{action['gcode']}    ; {desc}",
            "css": "crit" if is_crit else "indus",
            "src": "INDUS3D",
            "ts": ts_str,
        })
        offset += 1

    # Count stats
    slicer_count = sum(1 for l in merged if l["src"] == "Slicer")
    indus_count = sum(1 for l in merged if l["src"] == "INDUS3D")
    user_count = sum(1 for l in merged if l["src"] == "User")
    crit_count = sum(1 for l in merged if l["css"] == "crit")
    unique_alerts = set(a.get("alert_id", "") for a in actions if a.get("alert_id"))

    # Build rows
    rows = []
    for e in merged:
        txt = html_mod.escape(e["text"])
        src_label = ""
        if e["src"] == "INDUS3D":
            src_label = f'<span class="{e["css"]}">INDUS3D</span>'
        elif e["src"] == "User":
            src_label = '<span class="user">USER</span>'
        ts = e.get("ts", "")
        rows.append(f'<tr><td class="ln">{e["ln"]}</td><td class="ts">{ts}</td><td class="src">{src_label}</td><td class="{e["css"]}">{txt}</td></tr>')

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    css_style = """
body { font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 12px; line-height: 1.6; background: #1a1a2e; color: #a0a0b8; padding: 30px 40px; max-width: 1200px; margin: 0 auto; }
h1 { color: #e0e0ff; font-size: 20px; margin-bottom: 4px; }
.meta { color: #606080; font-size: 11px; margin-bottom: 24px; }
.legend { display: flex; gap: 24px; margin-bottom: 20px; flex-wrap: wrap; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.legend-swatch { width: 14px; height: 14px; border-radius: 3px; display: inline-block; }
table { width: 100%; border-collapse: collapse; }
tr { border-bottom: 1px solid #252540; }
tr:hover { background: #20203a; }
td { padding: 2px 10px; vertical-align: top; white-space: pre-wrap; word-break: break-all; }
td.ln { color: #404060; text-align: right; width: 50px; user-select: none; }
td.ts { color: #505070; width: 90px; font-size: 10px; }
td.src { width: 70px; font-size: 10px; font-weight: bold; }
.file { color: #8888aa; } .indus { color: #f0a050; background: #2a2010; }
.crit { color: #ff5555; background: #2a1515; font-weight: bold; }
.user { color: #5588ff; background: #151a2a; } .info { color: #50c878; }
.comment { color: #505070; font-style: italic; }
.stats { margin-top: 24px; padding: 16px; background: #20203a; border-radius: 8px; }
.stats h3 { color: #e0e0ff; margin: 0 0 8px; font-size: 14px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; }
.stat { font-size: 12px; } .stat-val { color: #f0a050; font-weight: bold; }
"""

    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Indus3D Annotated G-code — {html_mod.escape(filename)}</title>
<style>{css_style}</style></head><body>
<h1>Indus3D — Annotated G-code Export</h1>
<div class="meta">File: <strong>{html_mod.escape(filename)}</strong> | Generated: {now} | Indus3D Research Export</div>
<div class="legend">
<div class="legend-item"><span class="legend-swatch" style="background:#8888aa"></span> Original slicer G-code</div>
<div class="legend-item"><span class="legend-swatch" style="background:#f0a050"></span> Indus3D QC correction</div>
<div class="legend-item"><span class="legend-swatch" style="background:#ff5555"></span> Indus3D critical action</div>
<div class="legend-item"><span class="legend-swatch" style="background:#5588ff"></span> User manual command</div>
<div class="legend-item"><span class="legend-swatch" style="background:#505070"></span> Comment / informational</div>
</div>
<table><thead><tr><th style="text-align:right;color:#404060;width:50px">#</th><th style="color:#404060;width:90px">Time</th><th style="color:#404060;width:70px">Source</th><th style="color:#404060">G-code</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<div class="stats"><h3>Print Intervention Summary</h3><div class="stats-grid">
<div class="stat">Original G-code lines: <span class="stat-val">{slicer_count:,}</span></div>
<div class="stat">Indus3D injections: <span class="stat-val">{indus_count}</span></div>
<div class="stat">User commands: <span class="stat-val">{user_count}</span></div>
<div class="stat">Critical actions: <span class="stat-val">{crit_count}</span></div>
<div class="stat">Unique alert types: <span class="stat-val">{", ".join(sorted(unique_alerts)) or "None"}</span></div>
<div class="stat">Intervention rate: <span class="stat-val">{(indus_count / max(slicer_count, 1) * 100):.2f}%</span></div>
</div></div>
<p style="color:#404060;font-size:10px;margin-top:20px;text-align:center">Generated by Indus3D — Real-time 3D Printer Quality Control System</p>
</body></html>"""

    return Response(page, mimetype="text/html", headers={
        "Content-Disposition": f"attachment; filename={filename.replace('.gcode', '')}_annotated.html",
    })


# ── Print controls ────────────────────────────────────────────────────────────
@app.route("/api/v1/print/upload", methods=["POST"])
def upload_print():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f         = request.files["file"]
    start_now = request.args.get("start", "0") == "1"
    try:
        files_payload = {"file": (f.filename, f.stream, "application/octet-stream")}
        data_payload  = {"root": "gcodes"}
        if start_now:
            data_payload["print"] = "true"
        res = req.post(
            f"{settings.moonraker_url}/server/files/upload",
            files=files_payload, data=data_payload, timeout=30,
        )
        return jsonify({"status": "ok" if res.ok else "error", "filename": f.filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


for _action in ("pause", "resume", "cancel"):
    def _make_route(action):
        def _route():
            try:
                req.post(f"{settings.moonraker_url}/printer/print/{action}", timeout=5)
                return jsonify({"status": "ok"})
            except Exception as e:
                return jsonify({"error": str(e)}), 502
        _route.__name__ = f"print_{action}"
        return _route
    app.route(f"/api/v1/print/{_action}", methods=["POST"])(_make_route(_action))


@app.route("/api/v1/print/start", methods=["POST"])
def print_start():
    """Start printing a file already on the gcodes root — the file manager's
    'print' button. Upload-and-print is handled separately by
    /api/print/upload above; this is for files that are already there."""
    data = request.get_json(force=True, silent=True) or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        res = req.post(
            f"{settings.moonraker_url}/printer/print/start",
            params={"filename": filename}, timeout=10,
        )
        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ── Legacy HTTP endpoints (kept for backward compatibility) ───────────────────
@app.route("/api/v1/telemetry", methods=["GET"])
def get_telemetry():
    w = _worker(); d = w.latest if w else {}
    if not d:
        return jsonify({"x": 0, "y": 0, "z": 0, "extTemp": 0,
                        "bedTemp": 0, "state": "offline"})
    return jsonify({
        "x":              d.get("cmd_x", 0),
        "y":              d.get("cmd_y", 0),
        "z":              d.get("cmd_z", 0),
        "extTemp":        d.get("ext_temp", 0),
        "bedTemp":        d.get("bed_temp", 0),
        "state":          d.get("print_state", "unknown"),
        "filename":       d.get("filename", ""),
        "file_position":  d.get("file_position", 0),
        "progress":       d.get("progress", 0),
        "time_remaining": d.get("time_remaining", 0),
        "print_duration": d.get("print_duration", 0),
        "speed_factor":   d.get("speed_factor", 100),
        "flow_factor":    d.get("flow_factor", 100),
    })


@app.route("/api/v1/history", methods=["GET"])
def history():
    w = _worker()
    if w and hasattr(w, "print_history") and w.print_history:
        return jsonify(w.print_history[-20:])
    try:
        from db.models import get_connection
        conn = get_connection(); c = conn.cursor()
        c.execute("SELECT filename,status,timestamp,report_path,annotated_gcode_path FROM print_history "
                  "ORDER BY id DESC LIMIT 20")
        rows = [{"filename": r[0], "status": r[1], "timestamp": r[2], "report_path": r[3], "annotated_gcode_path": r[4]}
                for r in c.fetchall()]
        conn.close(); return jsonify(rows)
    except Exception:
        return jsonify([])


@app.route("/api/v1/environment", methods=["GET"])
def environment():
    w = _worker()
    # Sim worker has realistic simulated environment
    if w and hasattr(w, "environment"):
        return jsonify(w.environment)
    # Live mode — return zeros until BME280 is wired
    # NOTE: do NOT fall back to ext_temp (causes 200°C ambient reading)
    return jsonify({"temperature": 0.0, "humidity": 0.0})


@app.route("/api/v1/power", methods=["GET"])
def power():
    w = _worker()
    if w and hasattr(w, "power"):
        return jsonify(w.power)
    return jsonify({"voltage": 0.0, "current": 0.0, "power": 0.0})


from db.models import get_connection

def get_maintenance_rules():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT key, value FROM printer_config")
    config = dict(c.fetchall())
    conn.close()

    nozzle_mat = config.get("nozzle_material", "Brass")
    filament_type = config.get("filament_type", "Standard")
    structural_mat = config.get("structural_material", "PETG")

    # Dynamic Nozzle Calculation
    # Base standard hours
    nozzle_base_hours = {
        "Brass": 300,
        "Plated Copper": 400,
        "Stainless Steel": 500,
        "Hardened Steel": 2000,
        "Tungsten Carbide": 5000,
        "Ruby-tipped": 5000,
        "Diamond-tipped": 10000
    }.get(nozzle_mat, 300)

    # Abrasive multiplier
    if filament_type == "Abrasive":
        if nozzle_mat in ["Brass", "Plated Copper"]:
            nozzle_threshold = 10
        elif nozzle_mat == "Stainless Steel":
            nozzle_threshold = 50
        elif nozzle_mat == "Hardened Steel":
            nozzle_threshold = 500
        else:
            nozzle_threshold = 2000
    else:
        nozzle_threshold = nozzle_base_hours

    # Dynamic Structural Calculation
    # How many hours of heated bed cycles before assuming warp/degradation
    structural_threshold = {
        "PLA": 100,
        "PETG": 300,
        "ABS": 500,
        "ASA": 600,
        "PC": 800,
        "Nylon": 800,
        "Machined Aluminum": 10000,
        "Machined Steel": 20000
    }.get(structural_mat, 300)

    return [
        {"metric": "odometry_x_m",    "threshold": 500,  "msg": "Lubricate X-axis linear rail and lead screw", "type": "mechanical"},
        {"metric": "odometry_y_m",    "threshold": 500,  "msg": "Lubricate Y-axis rods and clean belt", "type": "mechanical"},
        {"metric": "odometry_z_m",    "threshold": 200,  "msg": "Lubricate Z-axis lead screw with PTFE grease", "type": "mechanical"},
        {"metric": "ext_heat_cycles", "threshold": 300,  "msg": "Inspect extruder heater cartridge and thermistor", "type": "mechanical"},
        {"metric": "bed_heat_cycles", "threshold": structural_threshold,  "msg": f"Inspect {structural_mat} structural parts for heat warping", "type": "structural"},
        {"metric": "nozzle_hours",    "threshold": nozzle_threshold,  "msg": f"Replace {nozzle_mat} nozzle ({filament_type} filament wear limit)", "type": "consumable"},
        {"metric": "filter_hours",    "threshold": 150,  "msg": "Replace carbon filter element", "type": "consumable"},
    ]

@app.route("/api/v1/maintenance", methods=["GET"])
def maintenance():
    w = _worker()
    if w and type(w).__name__ == "SimulatedTelemetryWorker":
        # Simulator uses its own in-memory state
        return jsonify({
            "hints": getattr(w, "maintenance_hints", []),
            "status": getattr(w, "maintenance_status", [])
        })
    
    # Real telemetry reads from SQLite
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT task_id, value FROM maintenance_counters")
        counters = {row[0]: row[1] for row in c.fetchall()}
        c.execute("SELECT key, value FROM printer_config")
        config = dict(c.fetchall())
        conn.close()
        
        status = []
        hints = []
        rules = get_maintenance_rules()
        for rule in rules:
            val = counters.get(rule["metric"], 0.0)
            status.append({
                "metric": rule["metric"],
                "value": val,
                "threshold": rule["threshold"],
                "msg": rule["msg"],
                "type": rule["type"]
            })
            if val >= rule["threshold"]:
                hints.append(rule["msg"])
        
        return jsonify({"hints": hints, "status": status, "config": config})
    except Exception as e:
        return jsonify({"hints": [], "status": [], "error": str(e)})

@app.route("/api/v1/maintenance/reset", methods=["POST"])
def reset_maintenance():
    task_id = request.json.get("task_id")
    if not task_id:
        return jsonify({"error": "task_id required"}), 400
        
    try:
        import time
        conn = get_connection()
        c = conn.cursor()
        # Reset the counter
        c.execute("INSERT OR REPLACE INTO maintenance_counters (task_id, value) VALUES (?, 0.0)", (task_id,))
        # Log the reset
        c.execute("INSERT INTO maintenance_logs (task_id, timestamp) VALUES (?, ?)", (task_id, time.time()))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/health", methods=["GET"])
def health():
    w    = _worker()
    mr_ok = False
    try:
        r = req.get(f"{settings.moonraker_url}/server/info", timeout=2)
        mr_ok = r.ok
    except Exception:
        pass
    return jsonify({
        "status":    "ok",
        "moonraker": mr_ok,
        "worker":    w is not None and bool(w.latest),
        "sim_mode":  w is not None and hasattr(w, "shape"),
    })



@app.route("/api/v1/history/<int:job_id>/measurements", methods=["POST"])
def add_measurements(job_id):
    data = request.json
    try:
        from db.models import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            UPDATE print_history 
            SET measured_x = ?, measured_y = ?, measured_z = ?, 
                operator_name = ?, work_order_id = ? 
            WHERE id = ?
        ''', (
            data.get("measured_x"),
            data.get("measured_y"),
            data.get("measured_z"),
            data.get("operator_name"),
            data.get("work_order_id"),
            job_id
        ))
        conn.commit()
        
        # We need the start and end time to regenerate the report
        # For simplicity, we just trigger it and let it fetch the bounds from twin_snapshots
        # Actually, let's look up the start/end bounds from twin_snapshots
        c.execute("SELECT MIN(timestamp), MAX(timestamp), filename FROM twin_snapshots WHERE filename = (SELECT filename FROM print_history WHERE id = ?) AND timestamp > (SELECT timestamp FROM print_history WHERE id = ?)", (job_id, job_id))
        row = c.fetchone()
        conn.close()
        
        # A simpler way: The old report was already generated with start_ts and end_ts. 
        # But we can just use the print_history timestamp.
        # It's better to just regenerate it using the earliest and latest snap for that print.
        # Actually, trigger_qa_report takes history_id, start_ts, end_ts, filename. 
        return jsonify({"success": True, "message": "Measurements saved. Run QA report again to include them."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _port_available(host: str, port: int) -> bool:
    """Quick TCP bind test — True if free, False if already taken. Doesn't
    hold the socket open, so app.run() binding it a moment later is safe
    (a narrow TOCTOU race exists but this is a diagnostic pre-check, not a
    security boundary — worst case is app.run() raises its own OSError
    same as before, just without this nicer message that one time)."""
    bind_host = "0.0.0.0" if host == "0.0.0.0" else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind_host, port))
            return True
        except OSError:
            return False


def run_server():
    port = settings.FLASK_PORT
    max_retries = 10
    
    for attempt in range(max_retries):
        if _port_available(settings.FLASK_HOST, port):
            break
        logging.warning(f"⚠️ Port {port} is in use on {settings.FLASK_HOST}, trying {port + 1}...")
        port += 1
    else:
        logging.error("=" * 70)
        logging.error(f"🔴 Could not find an open port in range {settings.FLASK_PORT}-{settings.FLASK_PORT + max_retries - 1} — Indus3D can't start.")
        logging.error("=" * 70)
        os._exit(1)

    # Note: If the port dynamically changed, a standard built frontend 
    # might not know where to connect unless it uses dynamic port hunting.
    if port != settings.FLASK_PORT:
        logging.info(f"🔀 PORT SWITCHED: Backend is running on port {port} instead of {settings.FLASK_PORT}")

    logging.info(f"🌐 API Server → http://{settings.FLASK_HOST}:{port}")
    logging.info(f"   Moonraker  → {settings.moonraker_url}")
    logging.info(f"   Webcam     → {settings.webcam_stream_url}")
    app.run(
        host=settings.FLASK_HOST,
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True
    )

@app.route("/api/v1/maintenance/config", methods=["POST"])
def update_maintenance_config():
    data = request.json
    try:
        conn = get_connection()
        c = conn.cursor()
        for key, value in data.items():
            if key in ["nozzle_material", "filament_type", "structural_material", "virtual_spool_weight_g", "virtual_spool_used_g", "virtual_spool_color", "virtual_spool_material"]:
                c.execute("INSERT OR REPLACE INTO printer_config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/v1/reports/<path:filename>", methods=["GET"])
def download_report(filename):
    import os
    from flask import send_from_directory
    reports_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
    return send_from_directory(reports_dir, filename)
