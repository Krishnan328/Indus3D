"""Small in-memory, per-IP sliding-window limiter for the Flask API.

Indus3D is normally a single-printer service on a private network, so a
database or external cache would be unnecessary operational weight. This
limiter protects the routes that can move or stop hardware and slows password
guessing without adding a runtime dependency. Its state intentionally resets
when the process restarts.
"""

from __future__ import annotations

from collections import defaultdict
import threading
import time

from flask import jsonify, request


# category -> (maximum requests, rolling window in seconds)
_LIMITS = {
    "login": (5, 5 * 60),
    "hardware_cmd": (10, 60),
    "default": (120, 60),
}
_BAN_AFTER_VIOLATIONS = 3
_VIOLATION_WINDOW_SECONDS = 60 * 60
_BAN_SECONDS = 24 * 60 * 60

# Kept module-level both for a single shared process-wide view and for the
# focused security tests. Keys are (remote IP, category) for request windows
# and IPs for bans/violations.
_requests: dict[tuple[str, str], list[float]] = defaultdict(list)
_violations: dict[str, list[float]] = defaultdict(list)
_bans: dict[str, float] = {}
_lock = threading.Lock()


def _client_ip() -> str:
    """Use Flask's resolved remote address without trusting arbitrary headers."""
    return request.remote_addr or "unknown"


def _category() -> str:
    path = request.path
    if request.method == "POST" and path == "/api/v1/auth/login":
        return "login"
    if request.method == "POST" and (
        path.startswith("/api/v1/printer/")
        or path.startswith("/api/v1/control/")
        or path.startswith("/api/v1/twin/action/")
    ):
        return "hardware_cmd"
    return "default"


def _prune(entries: list[float], now: float, window: float) -> list[float]:
    return [timestamp for timestamp in entries if now - timestamp < window]


def check_rate_limit(app):
    """Install the limiter once on *app*.

    ``install_auth_gate`` and the application factory both call this helper in
    existing deployments. The marker prevents a duplicate ``before_request``
    hook from applying each request twice.
    """
    if app.extensions.get("indus3d_rate_limiter"):
        return
    app.extensions["indus3d_rate_limiter"] = True

    @app.before_request
    def _limit_request():
        # Browser CORS preflight is not an API action and must never consume a
        # command allowance.
        if request.method == "OPTIONS":
            return None

        now = time.monotonic()
        ip = _client_ip()
        category = _category()
        limit, window = _LIMITS[category]

        with _lock:
            ban_expires = _bans.get(ip)
            if ban_expires:
                if ban_expires > now:
                    return jsonify({
                        "error": "IP temporarily banned after repeated rate-limit violations",
                        "category": category,
                        "retry_after": max(1, int(ban_expires - now)),
                    }), 403
                _bans.pop(ip, None)

            key = (ip, category)
            recent = _prune(_requests[key], now, window)
            _requests[key] = recent
            if len(recent) < limit:
                recent.append(now)
                return None

            violations = _prune(_violations[ip], now, _VIOLATION_WINDOW_SECONDS)
            violations.append(now)
            _violations[ip] = violations
            if len(violations) >= _BAN_AFTER_VIOLATIONS:
                _bans[ip] = now + _BAN_SECONDS

            retry_after = max(1, int(window - (now - recent[0])))
            return jsonify({
                "error": "Rate limit exceeded",
                "category": category,
                "retry_after": retry_after,
            }), 429
