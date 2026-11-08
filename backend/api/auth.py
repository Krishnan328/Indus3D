"""
api/auth.py
-------------
Single-tenant authentication for Indus3D.

Designed for zero-friction default — when INDUS3D_PASSWORD is unset in .env,
auth is entirely disabled and every route behaves exactly as it did before
this module existed. When set, all API routes require either:
  - A valid Flask session cookie (set by POST /api/auth/login), OR
  - An Authorization: Bearer <password> header (for scripts/cURL)
"""

import logging
import hmac
import os
import time
from flask import Blueprint, jsonify, request, session

from config.settings import settings

auth_bp = Blueprint("auth", __name__)

# ── Secret key persistence ──────────────────────────────────────────────────
def _get_secret_key_path() -> str:
    env_path = os.getenv("FLASK_SECRET_KEY_PATH")
    if env_path:
        return env_path
    code_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.access(code_dir, os.W_OK):
        return os.path.join(code_dir, ".flask_secret_key")
    data_home = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    key_dir = os.path.join(data_home, "indus3d")
    os.makedirs(key_dir, exist_ok=True)
    return os.path.join(key_dir, ".flask_secret_key")

_SECRET_KEY_PATH = _get_secret_key_path()

def get_or_create_secret_key() -> str:
    if settings.FLASK_SECRET_KEY:
        return settings.FLASK_SECRET_KEY
    if os.path.isfile(_SECRET_KEY_PATH):
        with open(_SECRET_KEY_PATH, "r") as f:
            key = f.read().strip()
            if key:
                return key
    key = os.urandom(32).hex()
    try:
        with open(_SECRET_KEY_PATH, "w") as f:
            f.write(key)
        os.chmod(_SECRET_KEY_PATH, 0o600)
    except OSError as e:
        logging.info(f"⚠️  Could not persist Flask secret key: {e}")
    return key


# ── Auth check ───────────────────────────────────────────────────────────────
def auth_required() -> bool:
    return bool(settings.INDUS3D_PASSWORD)

def _check_password(candidate: str) -> bool:
    return hmac.compare_digest(
        candidate.encode("utf-8"),
        settings.INDUS3D_PASSWORD.encode("utf-8"),
    )

def _is_authenticated() -> bool:
    if session.get("authenticated"):
        return True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return _check_password(token)
    return False

# ── Routes ───────────────────────────────────────────────────────────────────
@auth_bp.route("/api/v1/auth/login", methods=["POST"])
def login():
    if not auth_required():
        return jsonify({"status": "ok", "message": "Auth not enabled"}), 200

    data = request.get_json(force=True, silent=True) or {}
    password = data.get("password", "")

    if _check_password(password):
        session["authenticated"] = True
        return jsonify({"status": "ok"}), 200

    return jsonify({"error": "Invalid password"}), 401


@auth_bp.route("/api/v1/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"}), 200


@auth_bp.route("/api/v1/auth/status", methods=["GET"])
def auth_status():
    return jsonify({
        "auth_required": auth_required(),
        "authenticated": _is_authenticated() if auth_required() else True,
    }), 200

# ── before_request hook ─────────────────────────────────────────────────────
_ALLOWLIST = frozenset([
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/status",
    "/api/v1/health",
])

from api.rate_limiter import check_rate_limit

def install_auth_gate(app):
    check_rate_limit(app)
    
    @app.before_request
    def _enforce_auth():
        if not auth_required():
            return None
        # The SPA and its hashed assets have to remain reachable so it can
        # render LoginScreen and submit credentials.  Only API and WebSocket
        # routes expose printer state or controls; all of those remain gated.
        if not request.path.startswith("/api/") and request.path != "/ws":
            return None
        if request.path in _ALLOWLIST:
            return None
        if request.method == "OPTIONS":
            return None
        if not _is_authenticated():
            return jsonify({"error": "Authentication required"}), 401
        return None
