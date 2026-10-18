"""
api/routes/edge.py
--------------------
API surface for the optional vision-inspection companion device (see
backend/edge/inspector.py, backend/edge/watchdog.py). This device runs
separately from the main Indus3D backend — see requirements-vision.txt for
why — and talks to us over these three routes instead of hitting Moonraker
or the printer directly, so a detection goes through the same pause logic,
logging, LEDs, and notifications as every other alert in the app.
"""

import logging
import time

from flask import Blueprint, jsonify, request
import requests

from config.settings import settings
from config.loader import get_edge_inspection_cfg
from core import edge_inspector_state as state
from core.alert_actions import _log_action
from core.notifications import notify

edge_bp = Blueprint("edge", __name__)


@edge_bp.route("/config", methods=["GET"])
def get_config():
    return jsonify(get_edge_inspection_cfg())


@edge_bp.route("/config", methods=["POST"])
def set_config():
    from config.loader import update_edge_inspection_cfg
    body = request.get_json(silent=True) or {}
    known = {"edge_inspection_enabled", "edge_inspection_threshold_pct", "edge_inspection_cooldown_s"}
    overrides = {k: v for k, v in body.items() if k in known}
    if not overrides:
        return jsonify({"error": "No recognized edge inspection settings in request body."}), 400
    try:
        update_edge_inspection_cfg(overrides)
    except FileNotFoundError:
        return jsonify({"error": "indus_overrides.cfg not found on the server."}), 500
    except (TypeError, ValueError) as e:
        return jsonify({"error": f"Invalid value: {e}"}), 400
    return jsonify(get_edge_inspection_cfg())


@edge_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    """Called periodically (every few seconds) by a running edge script so
    the dashboard can show whether the companion device is actually
    connected right now — unlike everything else in Indus3D, this is a
    separate physical device that can be unplugged without the rest of the
    app otherwise knowing."""
    body = request.get_json(silent=True) or {}
    state.record_heartbeat({
        "device_id": body.get("device_id"),
        "detector": body.get("detector"),  # "yolo" | "motion"
    })
    return jsonify({"status": "ok"})


@edge_bp.route("/status", methods=["GET"])
def status():
    cfg = get_edge_inspection_cfg()
    out = state.get_status()
    out["config"] = {
        "enabled": bool(cfg.get("enabled", False)),
        "threshold_pct": cfg.get("threshold_pct", 70.0),
        "cooldown_s": cfg.get("cooldown_s", 120.0),
    }
    return jsonify(out)


@edge_bp.route("/inspection-alert", methods=["POST"])
def inspection_alert():
    """A detection from the companion device. Always records it (for the
    status endpoint / dashboard), but only runs the actual pause/log/LED/
    notify pipeline if inspection is enabled, confidence clears the
    configured threshold, and we're not still in the cooldown window from
    the last real trigger — otherwise a single ongoing failure would pause,
    get resumed, then immediately re-pause on the very next frame."""
    body = request.get_json(silent=True) or {}
    try:
        confidence = float(body.get("confidence", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "confidence must be a number"}), 400
    label = (body.get("label") or "anomaly").strip()
    detector = (body.get("detector") or "unknown").strip()

    state.record_detection(confidence, label, detector)

    cfg = get_edge_inspection_cfg()
    if not cfg.get("enabled", False):
        return jsonify({"status": "disabled"})

    threshold = cfg.get("threshold_pct", 70.0)
    if confidence < threshold:
        return jsonify({"status": "below_threshold", "threshold_pct": threshold})

    cooldown = cfg.get("cooldown_s", 120.0)
    if state.in_cooldown(cooldown):
        return jsonify({"status": "cooldown"})

    # Only worth pausing if there's actually something printing right now.
    try:
        r = requests.get(f"{settings.moonraker_url}/printer/objects/query?print_stats", timeout=3)
        print_state = r.json().get("result", {}).get("status", {}).get("print_stats", {}).get("state", "standby")
    except Exception as e:
        logging.info(f"🔴 Could not check print state for inspection alert: {e}")
        print_state = "standby"

    if print_state != "printing":
        return jsonify({"status": "not_printing"})

    state.mark_alert_fired()

    description = f"Vision inspector ({detector}) detected '{label}' at {confidence:.0f}% confidence"
    
    # ── Feature 2: Autonomous First-Layer Squish ──
    if label == "z_too_high":
        try:
            requests.post(f"{settings.moonraker_url}/printer/gcode/script", json={"script": "SET_GCODE_OFFSET Z_ADJUST=-0.01 MOVE=1"}, timeout=5)
            _log_action({"timestamp": time.time(), "alert_id": "z_offset_ai", "gcode": "SET_GCODE_OFFSET Z_ADJUST=-0.01", "description": "AI detected Z too high - Babystepping down", "status": "executed"})
        except Exception as e:
            logging.info(f"⚠️ Failed to baby-step: {e}")
        return jsonify({"status": "executed", "action": "babystep_down"})
        
    elif label == "z_too_low":
        try:
            requests.post(f"{settings.moonraker_url}/printer/gcode/script", json={"script": "SET_GCODE_OFFSET Z_ADJUST=0.01 MOVE=1"}, timeout=5)
            _log_action({"timestamp": time.time(), "alert_id": "z_offset_ai", "gcode": "SET_GCODE_OFFSET Z_ADJUST=0.01", "description": "AI detected Z too low - Babystepping up", "status": "executed"})
        except Exception as e:
            logging.info(f"⚠️ Failed to baby-step: {e}")
        return jsonify({"status": "executed", "action": "babystep_up"})

    # ── Feature 3: Auto-Abort & LED Spaghetti Alerts ──
    # If we get here, it's a catastrophic failure (e.g., 'Spaghetti Failure' or 'Part Detached')
    
    pause_ok = False
    try:
        res = requests.post(f"{settings.moonraker_url}/printer/print/pause", timeout=5)
        pause_ok = res.ok
    except Exception as e:
        description += f" — pause request failed: {e}"

    if pause_ok:
        description += " — print paused"
    else:
        description += " — PAUSE FAILED, printer may still be running"

    _log_action({
        "timestamp": time.time(),
        "alert_id": "edge_inspection",
        "gcode": "PAUSE" if pause_ok else "",
        "description": description,
        "status": "executed" if pause_ok else "failed",
    })

    notify(f"👁️ Indus3D Vision: {description}")

    try:
        from core.alert_actions import _flash_led_for_alert
        # Flash RED for catastrophic failures
        _flash_led_for_alert("critical", restore_key="paused" if pause_ok else "printing")
    except Exception as e:
        logging.info(f"⚠️  LED flash for vision alert skipped: {e}")

    return jsonify({"status": "executed" if pause_ok else "pause_failed", "description": description})
