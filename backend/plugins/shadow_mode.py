"""
plugins/shadow_mode.py  (A1)
-----------------------------
While the auto-pilot is OFF the quality controller normally computes and sends
nothing, which makes it impossible to judge what it would do. This plugin turns
on the controller's shadow run: a second, side-effect-free controller instance
computes the corrections every tick and this plugin keeps them for review.

Nothing is ever sent. The shadow controller has its own state (rate limits,
last-commanded values), so turning the auto-pilot on later starts the real
controller from a clean slate rather than from hypothetical values.

GET /api/v1/plugins/shadow_mode   latest + recent would-be commands
"""

import time
from collections import deque

PLUGIN_INFO = {
    "title": "Shadow mode",
    "description": "Records the corrective G-code the controller would send while the auto-pilot is off.",
}

_recent = deque(maxlen=200)   # {"ts", "command"}
_reasons = deque(maxlen=200)  # {"ts", "type", "value", "reason"}


def on_shadow(commands: list, ctx: dict) -> None:
    now = ctx.get("now", time.time())
    for c in commands:
        _recent.appendleft({"ts": now, "command": c})
    for c in ctx.get("corrections", []):
        _reasons.appendleft({k: c.get(k) for k in ("ts", "type", "value", "reason")})


def snapshot() -> dict:
    from digital_twin.quality_controller import quality_controller as qc
    return {
        "enabled": qc.shadow_enabled,
        "autopilot": qc.auto_pilot,
        "note": ("Shadow commands are only produced while the auto-pilot is OFF and a print is running; "
                 "they are never sent."),
        "commands": list(_recent),
        "corrections": list(_reasons),
    }


def register_hooks(hooks) -> None:
    from digital_twin.quality_controller import quality_controller
    quality_controller.enable_shadow()
    hooks.on("shadow.commands", on_shadow, priority=10)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_shadow_mode", __name__, url_prefix="/api/v1/plugins/shadow_mode")

    @bp.route("", methods=["GET"])
    def shadow_status():
        return jsonify(snapshot())

    app.register_blueprint(bp)
