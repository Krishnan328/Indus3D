"""
api/routes/printer.py
----------------------
Proxy routes for all Moonraker operations.

The frontend must NEVER call port 7125 directly.
Every Klipper/Moonraker interaction goes through these endpoints.
This ensures:
  - The backend is always the single network boundary
  - Works when the frontend dev machine ≠ the Pi (no direct Moonraker access)
  - Security: rate-limit, auth, and input validation can be added in one place
  - The simulator can override any of these for offline testing

Endpoints:
  GET  /api/printer/files/gcodes/<filename>  → stream gcode file
  DELETE /api/printer/files/gcodes/<filename> → delete a gcode file
  GET  /api/printer/files/list               → list all gcode files
  GET  /api/printer/files/metadata           → print time/filament/thumbnails for a file
  GET  /api/printer/config/list              → list config files
  GET  /api/printer/config/<filename>        → read a config file
  POST /api/printer/config/<filename>        → save a config file
  POST /api/printer/gcode                    → execute a gcode command
  POST /api/printer/firmware_restart         → FIRMWARE_RESTART
  GET  /api/printer/bedmesh                  → bed mesh data
  GET  /api/printer/cameras                  → list Crowsnest webcam streams
  GET  /api/printer/spoolman/status          → Spoolman connection + active spool_id
  GET  /api/printer/spoolman/spools          → list non-archived spools
  POST /api/printer/spoolman/active          → set/clear the active spool
  GET  /api/printer/power/devices            → list Moonraker [power] devices
  POST /api/printer/power/<device>/<action>  → manual on/off
  GET  /api/printer/power/cutoff_config      → read-only: is auto-cutoff armed
  GET  /api/config                           → client-safe config (webcam url, etc.)
"""

import logging
import requests
from flask import Blueprint, jsonify, request, Response, stream_with_context
from config.settings import settings

printer_bp = Blueprint("printer", __name__)

_TIMEOUT_SHORT = 5
_TIMEOUT_LONG  = 30   # file uploads / downloads


def _mr(path: str) -> str:
    """Build full Moonraker URL."""
    return f"{settings.moonraker_url}{path}"


def _forward_error(e: Exception, context: str = ""):
    msg = f"Moonraker unreachable{f' ({context})' if context else ''}: {e}"
    return jsonify({"error": msg, "moonraker": settings.moonraker_url}), 502


# ── Client configuration ──────────────────────────────────────────────────────

@printer_bp.route("/config", methods=["GET"])
def client_config():
    """
    Returns the configuration the frontend needs.
    No secrets — only what the browser legitimately uses.
    """
    return jsonify({
        "moonraker_url":    settings.moonraker_url,
        "webcam_stream_url": settings.webcam_stream_url,
        "flask_port":       settings.FLASK_PORT,
    })


# ── Camera / webcam list ──────────────────────────────────────────────────────

@printer_bp.route("/cameras", methods=["GET"])
def camera_list():
    """
    Returns all configured webcam streams from Moonraker's webcam list.
    Crowsnest registers each camera in Moonraker automatically.

    Response: [{ name, stream_url, snapshot_url, enabled }]
    """
    try:
        res = requests.get(_mr("/server/webcams/list"), timeout=_TIMEOUT_SHORT)
        if not res.ok:
            # Fall back to a single default stream
            return jsonify([{
                "name":         "default",
                "stream_url":   settings.webcam_stream_url,
                "snapshot_url": settings.webcam_stream_url.replace("stream", "snapshot"),
                "enabled":      True,
            }])

        webcams = res.json().get("result", {}).get("webcams", [])
        cameras = []
        for cam in webcams:
            stream  = cam.get("stream_url", "")
            snap    = cam.get("snapshot_url", "")
            # Crowsnest uses relative paths — prepend host
            if stream.startswith("/"):
                stream = f"http://{settings.MOONRAKER_HOST}{stream}"
            if snap.startswith("/"):
                snap = f"http://{settings.MOONRAKER_HOST}{snap}"
            cameras.append({
                "name":         cam.get("name", "Camera"),
                "stream_url":   stream,
                "snapshot_url": snap,
                "enabled":      cam.get("enabled", True),
                "rotation":     cam.get("rotation", 0),
                "flip_h":       cam.get("flip_horizontal", False),
                "flip_v":       cam.get("flip_vertical", False),
            })
        return jsonify(cameras)
    except Exception as e:
        # Return a single default stream so the UI degrades gracefully
        return jsonify([{
            "name":         "default",
            "stream_url":   settings.webcam_stream_url,
            "snapshot_url": "",
            "enabled":      True,
        }])


# ── G-code files ──────────────────────────────────────────────────────────────

@printer_bp.route("/files/gcodes/<path:filename>", methods=["GET"])
def get_gcode_file(filename: str):
    """
    Streams a G-code file from Moonraker to the frontend.
    Large files are streamed without buffering the full content in Flask.
    """
    # Sim mode: serve from simulator instead of Moonraker
    if filename.startswith("sim_"):
        import workers
        w = workers._active_worker
        if w and hasattr(w, "gcode_str") and w.gcode_str:
            return Response(
                w.gcode_str,
                mimetype="text/plain",
                headers={"Cache-Control": "no-cache"},
            )
        return jsonify({"error": "Sim G-code not ready yet"}), 503

    try:
        mr_res = requests.get(
            _mr(f"/server/files/gcodes/{filename}"),
            stream=True,
            timeout=_TIMEOUT_LONG,
        )
        if not mr_res.ok:
            return jsonify({"error": f"File not found: {filename}"}), mr_res.status_code

        return Response(
            stream_with_context(mr_res.iter_content(chunk_size=8192)),
            content_type=mr_res.headers.get("Content-Type", "text/plain"),
        )
    except Exception as e:
        return _forward_error(e, "gcode file")


@printer_bp.route("/files/list", methods=["GET"])
def list_gcode_files():
    try:
        res = requests.get(
            _mr("/server/files/list?root=gcodes"),
            timeout=_TIMEOUT_SHORT,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, "file list")


@printer_bp.route("/files/metadata", methods=["GET"])
def gcode_metadata():
    """Print-time estimate, filament usage, thumbnail list — everything the
    slicer embedded. Thumbnail images themselves are just gcode-root files
    (under .thumbs/) and can be fetched via the existing
    /files/gcodes/<path> route above using each thumbnail's relative_path."""
    filename = request.args.get("filename", "")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        res = requests.get(
            _mr("/server/files/metadata"),
            params={"filename": filename},
            timeout=_TIMEOUT_SHORT,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, f"metadata for {filename}")


@printer_bp.route("/files/gcodes/<path:filename>", methods=["DELETE"])
def delete_gcode_file(filename: str):
    if ".." in filename:
        return jsonify({"error": "invalid filename"}), 400
    try:
        res = requests.delete(
            _mr(f"/server/files/gcodes/{filename}"),
            timeout=_TIMEOUT_SHORT,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, f"delete {filename}")


# ── Config files ──────────────────────────────────────────────────────────────

@printer_bp.route("/config/list", methods=["GET"])
def list_config_files():
    try:
        res = requests.get(
            _mr("/server/files/list?root=config"),
            timeout=_TIMEOUT_SHORT,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, "config list")


@printer_bp.route("/config/<path:filename>", methods=["GET"])
def get_config_file(filename: str):
    try:
        res = requests.get(
            _mr(f"/server/files/config/{filename}"),
            timeout=_TIMEOUT_SHORT,
        )
        return Response(res.content, status=res.status_code,
                        content_type=res.headers.get("Content-Type", "text/plain"))
    except Exception as e:
        return _forward_error(e, f"config/{filename}")


@printer_bp.route("/config/<path:filename>", methods=["POST"])
def save_config_file(filename: str):
    import difflib, time, json
    from db.models import get_connection

    # Handle FormData file upload correctly
    if 'file' in request.files:
        file_obj = request.files['file']
        new_content = file_obj.read().decode('utf-8', errors='replace')
        content_for_mr = new_content.encode('utf-8')
    else:
        new_content = request.get_data(as_text=True)
        content_for_mr = request.get_data()

    try:
        old_res = requests.get(_mr(f"/server/files/config/{filename}"), timeout=3)
        old_content = old_res.text if old_res.ok else ""
    except:
        old_content = ""

    diff = "\n".join(difflib.unified_diff(
        fromfile=f"old_{filename}",
        tofile=f"new_{filename}"
    ))

    try:
        conn = get_connection()
        conn.execute("INSERT INTO config_history (timestamp, operator_name, config_snapshot_json, diff_summary) VALUES (?, ?, ?, ?)",
                     (time.time(), "Unknown (UI)", json.dumps({filename: new_content}), diff))
        # Get the id of the config we just saved
        c = conn.cursor()
        c.execute("SELECT last_insert_rowid()")
        config_id = c.fetchone()[0]
        # Also update the most recent active print?
        # Actually, if we just want it to be tied to prints, we should assign the config_id
        # when a print starts. We can do that later by looking up the max(config_history.id).
        conn.commit()
        conn.close()
    except Exception as e:
        import logging
        logging.error(f"Failed to save config_history: {e}")

    try:
        files = {"file": (filename, content_for_mr, "text/plain")}
        data  = {"root": "config"}
        res   = requests.post(
            _mr("/server/files/upload"),
            files=files, data=data,
            timeout=_TIMEOUT_LONG,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, f"save config/{filename}")


# ── G-code execution ──────────────────────────────────────────────────────────

# Safe command prefixes — anything not starting with these is rejected
_SAFE_PREFIXES = {
    # Motion
    "G0", "G1", "G2", "G3", "G4", "G28", "G29", "G90", "G91", "G92",
    # Firmware retraction (G10=retract, G11=recover)
    "G10", "G11",
    # Temperature
    "M104", "M105", "M106", "M107", "M109",
    "M140", "M190",
    # Info / wait / misc
    "M114", "M115", "M117", "M300", "M400", "M503",
    # Flow & speed overrides (QC loop uses these)
    "M220", "M221",
    # Emergency stop (safety critical — must always be allowed)
    "M112",
    # Filament change / pause
    "M600", "M0", "M1",
    # Motors off
    "M84", "M18",
    # Klipper extended — QC loop sends these every 5 s during autopilot
    "SET_PRESSURE_ADVANCE",
    "SET_VELOCITY_LIMIT",
    "SET_RETRACTION",
    "SET_GCODE_OFFSET",
    "SET_INPUT_SHAPER",
    # Bed mesh
    "BED_MESH_CALIBRATE", "BED_MESH_CLEAR",
    # Calibration
    "SHAPER_CALIBRATE", "ADXL_TEST", "PID_CALIBRATE",
    # Exclude object (used by exclude-object workflow)
    "EXCLUDE_OBJECT",
    # Save / restart
    "FIRMWARE_RESTART", "RESTART", "SAVE_CONFIG",
    # Tool change
    "T0", "T1", "T2", "T3",
}

def _is_safe_gcode(cmd: str) -> bool:
    upper = cmd.strip().upper()
    return any(upper.startswith(p) for p in _SAFE_PREFIXES)


@printer_bp.route("/gcode", methods=["POST"])
def send_gcode():
    data = request.json or {}
    cmd  = data.get("command", "").strip()
    if not cmd:
        return jsonify({"error": "No command"}), 400
    if not _is_safe_gcode(cmd):
        return jsonify({"error": f"Command not in safe list: {cmd}"}), 403
    try:
        res = requests.post(
            _mr("/printer/gcode/script"),
            params={"script": cmd},
            timeout=_TIMEOUT_SHORT,
        )
        return jsonify({"status": "ok" if res.ok else "error", "code": res.status_code})
    except Exception as e:
        return _forward_error(e, "gcode")


@printer_bp.route("/firmware_restart", methods=["POST"])
def firmware_restart():
    try:
        res = requests.post(
            _mr("/printer/gcode/script?script=FIRMWARE_RESTART"),
            timeout=_TIMEOUT_SHORT,
        )
        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return _forward_error(e, "firmware_restart")



# ── Host & Power Control ──────────────────────────────────────────────────────

@printer_bp.route("/restart", methods=["POST"])
def restart():
    try:
        import workers
        w = workers._active_worker
        if w and hasattr(w, "inject_gcode"):
            w.inject_gcode("RESTART")
            return jsonify({"status": "ok", "mode": "sim"})

        res = requests.post(
            _mr("/printer/restart"),
            timeout=_TIMEOUT_SHORT,
        )
        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return _forward_error(e, "restart")

@printer_bp.route("/emergency_stop", methods=["POST"])
def emergency_stop():
    try:
        import workers
        w = workers._active_worker
        if w and hasattr(w, "inject_gcode"):
            w.inject_gcode("M112")
            return jsonify({"status": "ok", "mode": "sim"})

        res = requests.post(
            _mr("/printer/emergency_stop"),
            timeout=_TIMEOUT_SHORT,
        )
        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return _forward_error(e, "emergency_stop")

@printer_bp.route("/machine/reboot", methods=["POST"])
def machine_reboot():
    try:
        res = requests.post(
            _mr("/machine/reboot"),
            timeout=_TIMEOUT_SHORT,
        )
        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return _forward_error(e, "machine/reboot")

@printer_bp.route("/machine/shutdown", methods=["POST"])
def machine_shutdown():
    try:
        res = requests.post(
            _mr("/machine/shutdown"),
            timeout=_TIMEOUT_SHORT,
        )
        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return _forward_error(e, "machine/shutdown")

# ── Bed mesh ──────────────────────────────────────────────────────────────────


@printer_bp.route("/bedmesh", methods=["GET"])
def bed_mesh():
    try:
        res = requests.get(
            _mr("/printer/objects/query?bed_mesh"),
            timeout=_TIMEOUT_SHORT,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, "bedmesh")


def _flash_led_state(state_key: str):
    """Best-effort: apply the configured LED color for a one-shot action
    (homing, probing). Never raises."""
    try:
        from config import printers as printer_registry
        from config import led_profiles
        from services import led_controller
        active_id = printer_registry.list_printers()["active"]
        profile = led_profiles.get_profile(active_id)
        if profile.get("enabled") and profile.get("led_names"):
            color = profile["colors"].get(state_key)
            if color:
                scaled = led_controller.scale_hex(color, profile.get("brightness", 100))
                led_controller.set_leds(profile["led_names"], scaled)
    except Exception as e:
        logging.info(f"⚠️  LED flash ({state_key}) skipped: {e}")

@printer_bp.route("/home", methods=["POST"])
def home_axes():
    data = request.get_json(silent=True) or {}
    axes = (data.get("axes") or "").strip().upper()
    if axes and not set(axes) <= set("XYZ"):
        return jsonify({"error": "axes must only contain X, Y, Z"}), 400
    cmd = f"G28 {' '.join(axes)}".strip() if axes else "G28"
    _flash_led_state("homing")
    try:
        res = requests.post(_mr(f"/printer/gcode/script?script={cmd}"), timeout=_TIMEOUT_LONG)
        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return _forward_error(e, "home")


@printer_bp.route("/bedmesh/calibrate", methods=["POST"])
def bed_mesh_calibrate():
    _flash_led_state("probing")
    try:
        res = requests.post(
            _mr("/printer/gcode/script?script=BED_MESH_CALIBRATE"),
            timeout=_TIMEOUT_LONG,
        )
        # Record the calibration timestamp on success
        if res.ok:
            try:
                from config import printers as printer_registry
                import datetime
                active_id = printer_registry.list_printers()["active"]
                printer_registry.set_last_calibration(active_id, datetime.datetime.now(datetime.timezone.utc).isoformat())
            except Exception as e:
                logging.info(f"⚠️ Failed to record bed mesh calibration time: {e}")

        return jsonify({"status": "ok" if res.ok else "error"})
    except Exception as e:
        return _forward_error(e, "bedmesh calibrate")


# ── Spoolman (filament inventory, via Moonraker's [spoolman] component) ────────
# Moonraker must have [spoolman] configured in moonraker.conf pointing at a
# running Spoolman instance — see docs/DEVELOPMENT.md. If it isn't configured,
# these all fail closed with a normal error response; nothing else in Indus3D
# depends on Spoolman being present.

@printer_bp.route("/spoolman/status", methods=["GET"])
def spoolman_status():
    """Whether Moonraker has an active websocket to Spoolman, and the
    currently-active spool_id (or None if tracking is off)."""
    try:
        res = requests.get(_mr("/server/spoolman/status"), timeout=_TIMEOUT_SHORT)
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, "spoolman status")


@printer_bp.route("/spoolman/spools", methods=["GET"])
def spoolman_list_spools():
    """List non-archived spools via Moonraker's Spoolman proxy.
    See https://donkie.github.io/Spoolman/ for the underlying schema."""
    try:
        res = requests.post(
            _mr("/server/spoolman/proxy"),
            json={
                "request_method": "GET",
                "path": "/v1/spool",
                "query": "archived=false",
            },
            timeout=_TIMEOUT_SHORT,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, "spoolman spool list")


@printer_bp.route("/spoolman/active", methods=["POST"])
def spoolman_set_active():
    """Set (or clear, with spool_id=null) the active spool Moonraker reports
    filament usage against."""
    data = request.get_json(force=True, silent=True) or {}
    spool_id = data.get("spool_id")
    try:
        res = requests.post(
            _mr("/server/spoolman/spool_id"),
            json={"spool_id": spool_id},
            timeout=_TIMEOUT_SHORT,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, "spoolman set active")


# ── Power devices (relays/smart plugs via Moonraker's [power] component) ──────
# Requires one or more [power <device>] sections in moonraker.conf. See
# indus_overrides.cfg for the automatic thermal-runaway cutoff config —
# these routes are for listing devices and manual on/off control.

@printer_bp.route("/power/devices", methods=["GET"])
def power_devices():
    try:
        res = requests.get(_mr("/machine/device_power/devices"), timeout=_TIMEOUT_SHORT)
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, "power devices")


@printer_bp.route("/power/<device>/<action>", methods=["POST"])
def power_set(device: str, action: str):
    if action not in ("on", "off"):
        return jsonify({"error": "action must be 'on' or 'off'"}), 400
    try:
        res = requests.post(
            _mr(f"/machine/device_power/{action}"),
            params={"device": device},
            timeout=_TIMEOUT_SHORT,
        )
        return (res.text, res.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return _forward_error(e, f"power {action} ({device})")


@printer_bp.route("/power/cutoff_config", methods=["GET"])
def power_cutoff_config():
    """Whether the automatic thermal-runaway power cutoff is configured —
    read-only, so the frontend can show it's armed without re-implementing
    indus_overrides.cfg parsing."""
    from config.loader import power_cfg
    return jsonify({
        "enabled": bool(power_cfg.get("cutoff_enabled")),
        "device":  power_cfg.get("cutoff_device") or None,
    })

@printer_bp.route("/macros", methods=["GET"])
def get_macros():
    try:
        res = req.get(f"{settings.moonraker_url}/printer/objects/list", timeout=5)
        if not res.ok:
            return jsonify({"error": "Failed to fetch from Moonraker"}), 502
        data = res.json().get("result", {}).get("objects", [])

        # Filter for gcode_macro and extract the name
        macros = [obj.replace("gcode_macro ", "") for obj in data if obj.startswith("gcode_macro ")]

        # Optionally, we could fetch help strings by querying /printer/objects/query?gcode_macro <name>
        # but just returning the names is enough for buttons.
        return jsonify({"macros": sorted(macros)})
    except Exception as e:
        return jsonify({"error": str(e)}), 502

# ── Multi-printer (switch-based, see config/printers.py) ────────────────────
# Not "N simultaneous connections" — one active Moonraker connection at a
# time, switchable from a saved list. Matches how Mainsail itself does it.

@printer_bp.route("/instances", methods=["GET"])
def list_printer_instances():
    from config import printers as printer_registry
    return jsonify(printer_registry.list_printers())

@printer_bp.route("/instances", methods=["POST"])
def add_printer_instance():
    from config import printers as printer_registry
    body = request.get_json(silent=True) or {}
    try:
        data = printer_registry.add_printer(body.get("name"), body.get("host"), body.get("port"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(data)

@printer_bp.route("/instances/<printer_id>", methods=["DELETE"])
def remove_printer_instance(printer_id):
    from config import printers as printer_registry
    try:
        data = printer_registry.remove_printer(printer_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(data)

@printer_bp.route("/instances/<printer_id>/activate", methods=["POST"])
def activate_printer_instance(printer_id):
    from config import printers as printer_registry
    from workers.manager import switch_active_printer

    target = printer_registry.get_printer(printer_id)
    if not target:
        return jsonify({"error": "Unknown printer id"}), 404
    if printer_id == printer_registry.list_printers()["active"]:
        return jsonify(printer_registry.list_printers())  # already active — no-op

    try:
        switch_active_printer(target["host"], target["port"])
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        logging.error(f"🔴 Printer switch to {target['host']}:{target['port']} failed: {e}")
        return jsonify({"error": f"Switch failed: {e}"}), 500

    data = printer_registry.mark_active(printer_id)
    return jsonify(data)


# ── LED control (see services/led_controller.py, config/led_profiles.py) ────

@printer_bp.route("/leds", methods=["GET"])
def list_leds():
    """LED hardware discovered from the printer's own Klipper config
    ([neopixel]/[led]/[dotstar]/[pca9533]/[pca9632] sections) — not
    something the user registers manually, since Klipper already knows."""
    from services import led_controller
    return jsonify({"leds": led_controller.discover_leds()})

@printer_bp.route("/leds/set", methods=["POST"])
def set_led_manual():
    """Direct, one-shot color set — for testing a color in the Settings UI.
    Does not touch the saved profile; the automatic state-coloring in
    workers/telemetry_worker.py will overwrite this on the next state
    check if a profile is enabled."""
    from services import led_controller
    body = request.get_json(silent=True) or {}
    name = (body.get("led_name") or "").strip()
    color = body.get("color")
    if not name:
        return jsonify({"error": "led_name is required"}), 400
    try:
        led_controller.hex_to_rgb01(color)  # validate before sending
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    ok = led_controller.set_led(name, color)
    if not ok:
        return jsonify({"error": "Could not reach the printer to set the LED color"}), 502
    return jsonify({"status": "ok"})


@printer_bp.route("/led_profile", methods=["GET"])
def get_led_profile():
    from config import led_profiles
    from config import printers as printer_registry
    active_id = printer_registry.list_printers()["active"]
    return jsonify(led_profiles.get_profile(active_id))


@printer_bp.route("/led_profile", methods=["POST"])
def save_led_profile():
    from config import led_profiles
    from config import printers as printer_registry
    body = request.get_json(silent=True) or {}
    active_id = printer_registry.list_printers()["active"]
    try:
        profile = led_profiles.save_profile(
            active_id,
            enabled=bool(body.get("enabled", False)),
            led_names=body.get("led_names"),
            brightness=body.get("brightness", 100),
            printing_gradient=bool(body.get("printing_gradient", False)),
            colors=body.get("colors") or {},
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(profile)


@printer_bp.route("/leds/off", methods=["POST"])
def leds_off():
    """Quick-control helper: turn off every LED the profile is configured
    to drive (or, if no profile is set up yet, every discovered LED) —
    the 'off' button on the dashboard LED card. Bypasses brightness
    scaling deliberately; off is off regardless of the brightness slider."""
    from config import led_profiles
    from config import printers as printer_registry
    from services import led_controller
    active_id = printer_registry.list_printers()["active"]
    profile = led_profiles.get_profile(active_id)
    names = profile.get("led_names") or [l["name"] for l in led_controller.discover_leds()]
    if not names:
        return jsonify({"error": "No LEDs found to turn off"}), 400
    ok = led_controller.set_leds(names, "#000000")
    if not ok:
        return jsonify({"error": "Could not reach the printer to turn off the LEDs"}), 502
    return jsonify({"status": "ok"})


@printer_bp.route("/led_profile/apply_state", methods=["POST"])
def apply_led_profile_state():
    """Quick-control helper for the dashboard LED card: push the profile's
    color for one named state right now, honoring brightness — e.g. an
    'idle'/off button that doesn't require opening Settings. Distinct from
    /leds/set, which sends an arbitrary color to an arbitrary LED; this
    always uses the *saved profile's* LEDs and colors."""
    from config import led_profiles
    from config import printers as printer_registry
    from services import led_controller
    body = request.get_json(silent=True) or {}
    state_key = (body.get("state") or "").strip()
    if state_key not in led_profiles.STATES:
        return jsonify({"error": f"state must be one of {led_profiles.STATES}"}), 400

    active_id = printer_registry.list_printers()["active"]
    profile = led_profiles.get_profile(active_id)
    if not profile.get("led_names"):
        return jsonify({"error": "No LEDs configured in the LED profile yet"}), 400

    color = led_controller.scale_hex(profile["colors"][state_key], profile.get("brightness", 100))
    ok = led_controller.set_leds(profile["led_names"], color)
    if not ok:
        return jsonify({"error": "Could not reach the printer to set the LED color"}), 502
    return jsonify({"status": "ok", "state": state_key, "color": color})
