"""Cross-client preferences; the SQLite copy is a fallback, not a second source of truth."""
import json
import sqlite3

from flask import Blueprint, jsonify, request

from api import system_host as sh
from db.models import get_connection

settings_sync_bp = Blueprint("settings_sync_bp", __name__)
NAMESPACE = "indus3d"
KEY = "preferences"
MAX_BYTES = 64 * 1024


def _read_local():
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM printer_config WHERE key = 'ui_settings_sync'").fetchone()
        value = json.loads(row[0]) if row and row[0] else {}
        return value if isinstance(value, dict) else {}
    finally:
        conn.close()


@settings_sync_bp.route("", methods=["GET"])
def get_settings():
    try:
        result = sh.call("GET", f"/server/database/item?namespace={NAMESPACE}&key={KEY}")
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise ValueError("Invalid preference data")
        return jsonify({"ok": True, "source": "moonraker", "settings": value})
    except (sh.Unsupported, sh.Unreachable, sh.Refused, ValueError):
        try:
            return jsonify({"ok": True, "source": "local", "settings": _read_local()})
        except (sqlite3.Error, OSError, ValueError):
            return jsonify({"ok": False, "error": "Preferences are unavailable", "settings": {}}), 503


@settings_sync_bp.route("", methods=["POST"])
def save_settings():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "JSON object required"}), 400
    value = body.get("settings", body)
    if not isinstance(value, dict):
        return jsonify({"ok": False, "error": "settings must be an object"}), 400
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Preferences must contain valid JSON values"}), 400
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        return jsonify({"ok": False, "error": "Preferences are too large"}), 413

    remote_ok = False
    try:
        sh.call("POST", "/server/database/item", {"namespace": NAMESPACE, "key": KEY, "value": value})
        remote_ok = True
    except (sh.Unsupported, sh.Unreachable, sh.Refused):
        pass
    local_ok = False
    try:
        conn = get_connection()
        try:
            conn.execute("INSERT OR REPLACE INTO printer_config (key, value) VALUES ('ui_settings_sync', ?)", (encoded,))
            conn.commit()
            local_ok = True
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass
    if not remote_ok and not local_ok:
        return jsonify({"ok": False, "error": "Preferences could not be saved"}), 503
    response = {"ok": True, "source": "moonraker" if remote_ok else "local", "settings": value}
    if not remote_ok:
        response["warning"] = "Saved locally only; other devices cannot retrieve these changes yet."
    elif not local_ok:
        response["warning"] = "Remote save succeeded but the local fallback could not be updated."
    return jsonify(response)
