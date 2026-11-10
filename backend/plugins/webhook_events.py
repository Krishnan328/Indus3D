"""
plugins/webhook_events.py  (F3)
--------------------------------
Forwards Indus3D notifications (print complete/failed, runaway, watchdog,
thermal-sanity, sensor faults, vision detections, ...) to any HTTP endpoint,
so a remote-monitoring service or your own automation sees what Indus3D
detected. It adds one channel to core.notifications, so everything that
already calls notify() is forwarded; nothing else changes.

This is a generic signed webhook, not an Obico/OctoEverywhere API client: those
services need their own account-linked agents. Point this at a service that
accepts a webhook, or at a small relay of your own.

INDUS3D_WEBHOOK_URLS    comma-separated URLs (empty = disabled)
INDUS3D_WEBHOOK_SECRET  optional; adds  X-Indus3D-Signature: sha256=<hmac of the body>

Body: {"source":"indus3d","message":…,"ts":…,"print_state":…,"filename":…}

GET /api/v1/plugins/webhook_events    recent deliveries (host only, never secrets)
"""

import hashlib
import hmac
import json
import logging
import os
import time
from collections import deque
from urllib.parse import urlparse

PLUGIN_INFO = {
    "title": "Webhook events",
    "description": "Forwards every notification as a signed webhook for remote monitoring/automation.",
}

deliveries = deque(maxlen=50)


def _urls():
    return [u.strip() for u in os.environ.get("INDUS3D_WEBHOOK_URLS", "").split(",") if u.strip()]


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def build_body(message: str) -> bytes:
    from plugins._common import latest_telemetry
    t = latest_telemetry()
    return json.dumps({"source": "indus3d", "message": message, "ts": time.time(),
                       "print_state": t.get("print_state"), "filename": t.get("filename")}).encode()


def _send_webhook(message: str) -> str:
    """Notification channel: 'sent', 'skipped' (not configured) or 'failed'."""
    urls = _urls()
    if not urls:
        return "skipped"
    import requests
    body = build_body(message)
    headers = {"Content-Type": "application/json"}
    secret = os.environ.get("INDUS3D_WEBHOOK_SECRET", "")
    if secret:
        headers["X-Indus3D-Signature"] = sign(secret, body)
    ok_all = True
    for url in urls:
        try:
            res = requests.post(url, data=body, headers=headers, timeout=5)
            ok = res.ok
        except Exception as e:  # noqa: BLE001
            logging.info(f"🔴 webhook to {urlparse(url).netloc} failed: {e}")
            ok = False
        deliveries.appendleft({"ts": time.time(), "host": urlparse(url).netloc, "ok": ok})
        ok_all &= ok
    return "sent" if ok_all else "failed"


def register_hooks(hooks) -> None:
    from core import notifications
    if not any(c.__name__ == "_send_webhook" for c in notifications._CHANNELS):
        notifications._CHANNELS.append(_send_webhook)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_webhook_events", __name__, url_prefix="/api/v1/plugins/webhook_events")

    @bp.route("", methods=["GET"])
    def webhook_status():
        return jsonify({"configured": len(_urls()), "signed": bool(os.environ.get("INDUS3D_WEBHOOK_SECRET")),
                        "recent": list(deliveries)})

    app.register_blueprint(bp)
