"""
core/alert_actions.py
-----------------------
Automated corrective responses to alert conditions.

Rules:
- CRITICAL alerts (thermal runaway) → act immediately, regardless of print state
- WARN alerts → only act during active printing, never during idle/standby
- Each alert ID maps to a G-code command and a human-readable description
- Every execution is logged to the action_log table in the DB
"""

import logging
import time
from services.moonraker_client import MoonrakerClient
from config.loader import get_power_cfg
from config.settings import settings
from core.notifications import notify
from db.models import get_connection

_client = MoonrakerClient()

# Alert IDs eligible for the power-cutoff response, on top of their G-code
# action. Deliberately a short, explicit list — this is not something every
# alert type should be able to trigger.
_POWER_CUTOFF_ELIGIBLE = {"ext_runaway", "bed_runaway"}


def _flash_led_for_alert(severity: str, restore_key: str = None):
    """Best-effort: pulse the configured 'alert' color a few times, then
    settle on whichever steady color actually applies afterward. Critical
    alerts (M112) leave the printer halted, so they settle on 'error';
    warn-level alerts only ever fire mid-print (see the severity check in
    execute_alert_action), so they settle back on 'printing'. Callers with
    a state that doesn't map cleanly to "critical"/"warn" (e.g. the vision
    inspector's pause, which lands on Klipper's own 'paused' state, not
    'error') can pass restore_key explicitly instead. Never raises — a
    misconfigured or absent LED must not affect the alert response itself,
    which is already underway by the time this runs."""
    try:
        from config import printers as printer_registry
        from config import led_profiles
        from services import led_controller
        active_id = printer_registry.list_printers()["active"]
        profile = led_profiles.get_profile(active_id)
        if not profile.get("enabled") or not profile.get("led_names"):
            return
        if restore_key is None:
            restore_key = "error" if severity == "critical" else "printing"
        flash_color = led_controller.scale_hex(profile["colors"]["alert"], profile.get("brightness", 100))
        restore_color = led_controller.scale_hex(profile["colors"][restore_key], profile.get("brightness", 100))
        led_controller.flash(profile["led_names"], flash_color, restore_hex=restore_color)
    except Exception as e:
        logging.info(f"⚠️  LED alert flash skipped: {e}")

# ── Alert → corrective action mapping ─────────────────────────────────────────
ALERT_ACTIONS = {
    "ext_runaway": {
        "gcode":       "M112",
        "description": "Emergency stop — extruder thermal runaway",
        "severity":    "critical",
    },
    "bed_runaway": {
        "gcode":       "M112",
        "description": "Emergency stop — bed thermal runaway",
        "severity":    "critical",
    },
    "lag": {
        "gcode":       "M220 S80",
        "description": "Speed reduced to 80% — position lag detected",
        "severity":    "warn",
    },
    "under_ext": {
        "gcode":       "M221 S110",
        "description": "Flow rate increased to 110% — under-extrusion detected",
        "severity":    "warn",
    },
    "over_ext": {
        "gcode":       "M221 S90",
        "description": "Flow rate reduced to 90% — over-extrusion detected",
        "severity":    "warn",
    },
    # Belt stress and heat cycles are informational only — no automatic G-code action
    "stress_X":    {"gcode": None, "description": "X-axis belt stress high — inspect belt tension", "severity": "info"},
    "stress_Y":    {"gcode": None, "description": "Y-axis belt stress high — inspect belt tension", "severity": "info"},
    "stress_Z":    {"gcode": None, "description": "Z-axis stress high — check lead screw",          "severity": "info"},
    "ext_cycles":  {"gcode": None, "description": "Extruder heat cycles high — inspect heater",     "severity": "info"},
    "bed_cycles":  {"gcode": None, "description": "Bed heat cycles high — inspect bed wiring",      "severity": "info"},
    # Collision / crash detected by the Rust fast-path detector
    "collision_detected": {
        "gcode":       "PAUSE",
        "description": "Print paused — g-force spike detected (possible crash or layer knock)",
        "severity":    "critical",
    },
}

# Track which alerts have already triggered an action in this session
# to avoid repeating the same G-code on every tick
_actioned: set = set()


def execute_alert_action(alert_id: str, print_state: str) -> dict:
    """
    Execute the corrective action for a given alert.
    Returns a result dict with status and description.
    Safe to call on every telemetry tick — deduplicates internally.
    """
    action = ALERT_ACTIONS.get(alert_id)
    if not action:
        return {"status": "no_action_defined", "alert_id": alert_id}

    # No G-code action for informational alerts
    if not action["gcode"]:
        return {"status": "informational_only", "alert_id": alert_id,
                "description": action["description"]}

    # Deduplicate — don't send the same G-code twice for the same alert session
    if alert_id in _actioned:
        return {"status": "already_actioned", "alert_id": alert_id}

    # Warn-level: only act during printing
    if action["severity"] == "warn" and print_state != "printing":
        return {"status": "skipped_not_printing", "alert_id": alert_id}

    success = _client.send_gcode(action["gcode"])
    _actioned.add(alert_id)

    description = action["description"]

    # Physical power cutoff — opt-in, only for the runaway alert IDs, only
    # if indus_overrides.cfg has power_cutoff_enabled=true and a device
    # configured. See indus_overrides.cfg for why this exists alongside
    # M112 rather than instead of it.
    cutoff_cfg = get_power_cfg()
    if alert_id in _POWER_CUTOFF_ELIGIBLE and cutoff_cfg.get("cutoff_enabled") and cutoff_cfg.get("cutoff_device"):
        device = cutoff_cfg["cutoff_device"]
        cut_ok = _client.set_power(device, "off")
        description += f" — power cutoff to '{device}' {'succeeded' if cut_ok else 'FAILED (check locked_while_printing)'}"

    if action["severity"] == "critical" or (action["severity"] == "warn" and settings.NOTIFY_ON_WARN):
        notify(f"⚠️ Indus3D: {description}")

    _flash_led_for_alert(action["severity"])

    result = {
        "status":      "executed" if success else "failed",
        "alert_id":    alert_id,
        "gcode":       action["gcode"],
        "description": description,
        "severity":    action["severity"],
        "timestamp":   time.time(),
    }

    _log_action(result)
    return result


def clear_actioned(alert_id: str):
    """
    Call when an alert clears (condition resolved) so the action
    can trigger again if the condition reoccurs.
    """
    _actioned.discard(alert_id)


def clear_all_actioned():
    """Call at print start/end to reset the deduplication set."""
    _actioned.clear()


def get_action_log(limit: int = 50) -> list:
    """Retrieve action log from DB for display in the frontend."""
    try:
        conn = get_connection()
        c    = conn.cursor()
        c.execute("""
            SELECT timestamp, alert_id, gcode, description, status
            FROM action_log
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        cols = [d[0] for d in c.description]
        rows = [dict(zip(cols, r)) for r in c.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def _log_action(result: dict):
    try:
        conn = get_connection()
        c    = conn.cursor()
        c.execute("""
            INSERT INTO action_log (timestamp, alert_id, gcode, description, status)
            VALUES (?, ?, ?, ?, ?)
        """, (
            result["timestamp"],
            result["alert_id"],
            result["gcode"],
            result["description"],
            result["status"],
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.info(f"⚠️  action_log DB: {e}")
