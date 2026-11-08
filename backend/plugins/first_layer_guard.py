"""
plugins/first_layer_guard.py  (B2)
-----------------------------------
Bed adhesion is decided in the first layer, and that is exactly where an
untuned closed loop can do the most harm. While the nozzle is below
INDUS3D_FIRST_LAYER_Z_MM (default 0.8 mm commanded Z) during a print, the
guard drops quality-controller commands.

INDUS3D_FIRST_LAYER_BLOCK   "all" (default) or a comma list of families to
                            block: flow,speed,pa,nozzle_temp,fan,velocity,
                            retraction,shaper
Safety commands (PAUSE, M112, CANCEL_PRINT) always pass. Dropped commands are
recorded as vetoes, so the audit trail shows what the guard held back.

GET /api/v1/plugins/first_layer_guard
"""

import os
from collections import deque

from core.plugin_hooks import ctx_veto
from plugins.arbiter import family_of

PLUGIN_INFO = {
    "title": "First-layer guard",
    "description": "Keeps the controller's hands off the printer during the first layer(s).",
}

ALWAYS_PASS = {"PAUSE", "M112", "CANCEL_PRINT"}


class FirstLayerGuard:
    def __init__(self, z_limit=None, block=None):
        self.z_limit = float(os.environ.get("INDUS3D_FIRST_LAYER_Z_MM", 0.8)) if z_limit is None else z_limit
        raw = os.environ.get("INDUS3D_FIRST_LAYER_BLOCK", "all") if block is None else block
        self.block_all = str(raw).strip().lower() == "all"
        self.block = set() if self.block_all else {f.strip() for f in str(raw).split(",") if f.strip()}
        self.blocked_total = 0
        self.recent = deque(maxlen=50)

    def in_first_layer(self, snap: dict) -> bool:
        if snap.get("print_state") != "printing":
            return False
        z = snap.get("cmd_z", snap.get("live_z"))
        return z is not None and z < self.z_limit

    def filter(self, commands, ctx):
        snap = ctx.get("snap") or {}
        if not self.in_first_layer(snap):
            return commands
        kept = []
        for cmd in commands:
            token = cmd.strip().split(None, 1)[0].upper() if cmd.strip() else ""
            fam = family_of(cmd)
            if token in ALWAYS_PASS or not (self.block_all or fam in self.block):
                kept.append(cmd)
                continue
            ctx_veto(ctx, cmd, "first_layer_guard",
                     f"nozzle at Z={snap.get('cmd_z', snap.get('live_z'))} below {self.z_limit} mm")
            self.blocked_total += 1
            self.recent.appendleft({"ts": ctx.get("now"), "command": cmd})
        return kept

    def status(self):
        return {"z_limit_mm": self.z_limit, "blocks": "all" if self.block_all else sorted(self.block),
                "blocked_total": self.blocked_total, "recent": list(self.recent)}


guard = FirstLayerGuard()


def register_hooks(hooks) -> None:
    hooks.on("commands.filter", guard.filter, priority=15)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_first_layer_guard", __name__, url_prefix="/api/v1/plugins/first_layer_guard")

    @bp.route("", methods=["GET"])
    def guard_status():
        return jsonify(guard.status())

    app.register_blueprint(bp)
