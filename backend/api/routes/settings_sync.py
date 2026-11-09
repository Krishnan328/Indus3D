"""
api/routes/settings_sync.py
---------------------------
Synchronizes user settings and UI preferences across client devices
via Moonraker's database (/server/database/item?namespace=indus3d).
Falls back to local sqlite printer_config if Moonraker database is unreachable.
"""

import json
from flask import Blueprint, jsonify, request
from api import system_host as sh
from db.models import get_connection

settings_sync_bp = Blueprint("settings_sync_bp", __name__)

NAMESPACE = "indus3d"


@settings_sync_bp.route("", methods=["GET"])
def get_settings():
    """Retrieve synced settings from Moonraker database or fallback to SQLite."""
    try:
        res = sh.call("GET", f"/server/database/item?namespace={NAMESPACE}")
        val = res.get("value", {}) if isinstance(res, dict) else {}
        return jsonify({"ok": True, "source": "moonraker", "settings": val})
    except Exception:
        # Fallback to local printer_config
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT value FROM printer_config WHERE key = 'ui_settings_sync'")
            row = c.fetchone()
            conn.close()
            val = json.loads(row[0]) if row and row[0] else {}
            return jsonify({"ok": True, "source": "local", "settings": val})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "settings": {}}), 200


@settings_sync_bp.route("", methods=["POST"])
def save_settings():
    """Save synced settings to Moonraker database and cache in SQLite."""
    body = request.get_json(silent=True) or {}
    settings_data = body.get("settings", body)
    settings_str = json.dumps(settings_data)

    source = "local"
    try:
        sh.call("POST", "/server/database/item", {
            "namespace": NAMESPACE,
            "key": "preferences",
            "value": settings_data,
        })
        source = "moonraker"
    except Exception:
        pass

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO printer_config (key, value) VALUES ('ui_settings_sync', ?)", (settings_str,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return jsonify({"ok": True, "source": source, "settings": settings_data})
