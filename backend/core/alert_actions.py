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

import time
from services.moonraker_client import MoonrakerClient
from db.models import get_connection

_client = MoonrakerClient()

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

    result = {
        "status":      "executed" if success else "failed",
        "alert_id":    alert_id,
        "gcode":       action["gcode"],
        "description": action["description"],
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
        print(f"⚠️  action_log DB: {e}")
