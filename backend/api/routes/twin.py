import logging
from flask import Blueprint, jsonify, request, send_file
from digital_twin.kinematic_model import kinematic_model
from digital_twin.snapshot_logger import get_recent_snapshots
from core.alert_actions import execute_alert_action, get_action_log, clear_all_actioned
from core.notifications import any_channel_configured
from core.timelapse import list_timelapses, current_job as timelapse_job
from core.shaper_tuner import current_job as shaper_job, apply_result as apply_shaper_result, set_bed_mass
from digital_twin.quality_controller import quality_controller
from config.settings import settings
from config.loader import get_timelapse_cfg, update_timelapse_cfg
import os

twin_bp = Blueprint("twin", __name__)


def _latest():
    import workers
    w = workers._active_worker
    return w.latest if w else {}


@twin_bp.route("/notifications/status", methods=["GET"])
def notifications_status():
    """Read-only. Credentials live in .env on the device, not editable
    through the UI — this just tells the frontend whether anything is
    configured, so it can show an honest status instead of a dead toggle."""
    return jsonify({
        "configured": any_channel_configured(),
        "channels": {
            "discord":  bool(settings.DISCORD_WEBHOOK_URL),
            "telegram": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
        },
        "notify_on_warn": settings.NOTIFY_ON_WARN,
    })


@twin_bp.route("/state", methods=["GET"])
def twin_state():
    return jsonify(_latest())


@twin_bp.route("/timelapse/list", methods=["GET"])
def timelapse_list():
    return jsonify(list_timelapses())


@twin_bp.route("/timelapse/status", methods=["GET"])
def timelapse_status():
    """Whether a timelapse is currently being recorded, for a live indicator
    — not the historical list above."""
    return jsonify({
        "active": timelapse_job.active,
        "frame_count": timelapse_job.frame_count if timelapse_job.active else 0,
    })


@twin_bp.route("/timelapse/config", methods=["GET"])
def timelapse_config_get():
    """Current timelapse_* settings from indus_overrides.cfg, for the
    Settings > Timelapse tab. Read-only companion to the POST below."""
    return jsonify(get_timelapse_cfg())


@twin_bp.route("/timelapse/config", methods=["POST"])
def timelapse_config_set():
    """Persist timelapse_* settings to indus_overrides.cfg and apply them
    immediately (no restart needed — the next print picks up the new mode/
    interval/fps). Rejects an in-progress capture to avoid a mode change
    mid-job leaving mismatched frames."""
    if timelapse_job.active:
        return jsonify({"error": "Cannot change timelapse settings while a capture is in progress."}), 409
    body = request.get_json(silent=True) or {}
    known = {"timelapse_enabled", "timelapse_mode", "timelapse_interval_s", "timelapse_fps"}
    overrides = {k: v for k, v in body.items() if k in known}
    if not overrides:
        return jsonify({"error": "No recognized timelapse settings in request body."}), 400
    try:
        update_timelapse_cfg(overrides)
    except FileNotFoundError:
        return jsonify({"error": "indus_overrides.cfg not found on the server."}), 500
    except (TypeError, ValueError) as e:
        return jsonify({"error": f"Invalid value: {e}"}), 400
    return jsonify(get_timelapse_cfg())


@twin_bp.route("/timelapse/<job_id>/video", methods=["GET"])
def timelapse_video(job_id: str):
    # job_id comes from list_timelapses(), which only ever returns directory
    # names it found under TIMELAPSE_DIR itself — but this is still a path
    # segment from a URL, so validate it the same way a filename would be
    # before it ever touches the filesystem.
    if job_id != os.path.basename(job_id) or ".." in job_id:
        return jsonify({"error": "invalid job id"}), 400
    path = os.path.join(settings.TIMELAPSE_DIR, job_id, "timelapse.mp4")
    if not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    return send_file(path, mimetype="video/mp4")


# ── Input-shaper tuner ───────────────────────────────────────────────────────
@twin_bp.route("/shaper/current", methods=["GET"])
def shaper_current():
    return jsonify({
        "freq": getattr(quality_controller, "_f_baseline_y", 0),
        "bed_mass_g": getattr(quality_controller, "_m_baseline_g", 0),
        "shaper_type": getattr(quality_controller, "_shaper_type_y", "mzv"),
    })


@twin_bp.route("/shaper/calibrate", methods=["POST"])
def shaper_calibrate():
    data = request.get_json(force=True, silent=True) or {}
    if data.get("confirmed") is not True:
        return jsonify({"error": "Explicit confirmation is required before moving the printer"}), 412
    if _latest().get("print_state") in ("printing", "paused"):
        return jsonify({"error": "Shaper calibration cannot run during a print"}), 409
    if data.get("axis", "y").lower() != "y":
        return jsonify({"error": "Only the Y axis is supported by this tuner"}), 400
    return jsonify(shaper_job.start("y"))


@twin_bp.route("/shaper/status", methods=["GET"])
def shaper_status():
    return jsonify(shaper_job.status_dict())


@twin_bp.route("/shaper/apply", methods=["POST"])
def shaper_apply():
    data = request.get_json(force=True, silent=True) or {}
    if data.get("confirmed") is not True:
        return jsonify({"error": "Explicit confirmation is required before saving configuration"}), 412
    try:
        shaper_type, freq = data["shaper_type"], float(data["freq"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "shaper_type and numeric freq are required"}), 400
    return jsonify(apply_shaper_result(shaper_type, freq))


@twin_bp.route("/shaper/bed_mass", methods=["POST"])
def shaper_bed_mass():
    data = request.get_json(force=True, silent=True) or {}
    try:
        grams = float(data["grams"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "numeric grams required"}), 400
    return jsonify(set_bed_mass(grams))


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

@twin_bp.route("/stats/lifetime", methods=["GET"])
def get_lifetime_stats():
    from db.models import get_connection
    try:
        conn = get_connection()
        c = conn.cursor()

        # Total print hours and total power
        c.execute("SELECT SUM(print_time_seconds), SUM(power_used_wh), SUM(filament_used_g), SUM(cost_usd) FROM print_history")
        row = c.fetchone()
        total_seconds = row[0] or 0.0
        total_power_wh = row[1] or 0.0
        total_fil_g = row[2] or 0.0
        total_cost = row[3] or 0.0

        # Success ratio
        c.execute("SELECT status, COUNT(*) FROM print_history GROUP BY status")
        status_counts = dict(c.fetchall())
        total_prints = sum(status_counts.values())

        # Odometry (Filament extruded lifetime)
        c.execute("SELECT travel_meters FROM odometry WHERE axis = 'E'")
        e_row = c.fetchone()
        filament_meters = e_row[0] if e_row else 0.0

        conn.close()

        return jsonify({
            "total_print_hours": round(total_seconds / 3600.0, 1),
            "total_power_kwh": round(total_power_wh / 1000.0, 2),
            "total_filament_g": round(total_fil_g, 1),
            "total_filament_meters": round(filament_meters, 1),
            "total_cost_usd": round(total_cost, 2),
            "status_counts": status_counts,
            "total_prints": total_prints,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@twin_bp.route("/exclude_object", methods=["POST"])
def exclude_object():
    obj_name = request.json.get("name")
    if not obj_name:
        return jsonify({"error": "name required"}), 400
    try:
        from api.server import _worker
        w = _worker()
        if w and type(w).__name__ == "SimulatedTelemetryWorker":
            w.inject_gcode(f"TOGGLE_EXCLUDE_OBJECT NAME={obj_name}")
            if hasattr(w, "excluded_objects"):
                if obj_name in w.excluded_objects:
                    w.excluded_objects.remove(obj_name)
                else:
                    w.excluded_objects.add(obj_name)
            return jsonify({"success": True, "sim": True})

        from services.moonraker_client import MoonrakerClient
        m = MoonrakerClient()
        res = m.send_gcode(f"EXCLUDE_OBJECT NAME={obj_name}")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@twin_bp.route("/auto-pilot", methods=["GET"])
def get_auto_pilot():
    return jsonify({"auto_pilot_enabled": quality_controller.auto_pilot})

@twin_bp.route("/auto-pilot", methods=["POST"])
def set_auto_pilot():
    data = request.get_json(force=True, silent=True) or {}
    enabled = data.get("enabled")
    if enabled is None:
        return jsonify({"error": "Missing 'enabled' boolean"}), 400
    quality_controller.auto_pilot = bool(enabled)
    return jsonify({"auto_pilot_enabled": quality_controller.auto_pilot})
