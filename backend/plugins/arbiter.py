"""
plugins/arbiter.py  (A4)
-------------------------
Makes sure only one controller writes each G-code "family" (M221 flow, M220
speed, pressure advance, ...). Two ways a second writer is handled:

1. Declared ownership — INDUS3D_ARBITER_EXTERNAL=flow,speed tells Indus3D that
   something else (e.g. the filament-sensor daemon's auto-flow, a slicer macro)
   owns those families; the quality controller never writes them.
2. Detected writers — Klipper reports the live M221/M220 factors. If they
   change and Indus3D did not just send that value, an external write is
   assumed and Indus3D yields that family for INDUS3D_ARBITER_YIELD_S seconds
   (default 30) instead of fighting it. Every yield is recorded as an event.

Dropped commands are recorded as vetoes, so the audit trail shows them.

GET /api/v1/plugins/arbiter    ownership, active yields, recent events
"""

import os
import re
import time
from collections import deque

from core.plugin_hooks import ctx_veto

PLUGIN_INFO = {
    "title": "Controller arbiter",
    "description": "Prevents Indus3D and other writers (sensor daemon, macros) fighting over M221/M220 and friends.",
}

FAMILIES = {
    "M221": "flow",
    "M220": "speed",
    "SET_PRESSURE_ADVANCE": "pa",
    "M104": "nozzle_temp",
    "M106": "fan",
    "SET_VELOCITY_LIMIT": "velocity",
    "SET_RETRACTION": "retraction",
    "SET_INPUT_SHAPER": "shaper",
}
# Families whose live value Klipper reports, so external writes are detectable.
OBSERVED = {"flow": "flow_factor", "speed": "speed_factor"}
GRACE_S = 5.0        # how long after our own send an observed change counts as ours
CHANGE_EPS = 0.5     # percent; smaller observed movement is noise
MATCH_EPS = 1.0

_S_VALUE = re.compile(r"\bS(-?\d+(?:\.\d+)?)", re.I)


def family_of(command: str):
    token = command.strip().split(None, 1)[0].upper() if command.strip() else ""
    return FAMILIES.get(token)


def s_value(command: str):
    m = _S_VALUE.search(command)
    return float(m.group(1)) if m else None


class Arbiter:
    def __init__(self, external=None, yield_s=None):
        env_ext = os.environ.get("INDUS3D_ARBITER_EXTERNAL", "")
        self.external = set(external) if external is not None else {
            f.strip() for f in env_ext.split(",") if f.strip()}
        self.yield_s = float(yield_s if yield_s is not None
                             else os.environ.get("INDUS3D_ARBITER_YIELD_S", 30))
        self.last_sent = {}     # family -> (value, t)
        self.prev_obs = {}
        self.yield_until = {}
        self.events = deque(maxlen=100)

    # hooks -----------------------------------------------------------------
    def filter(self, commands, ctx):
        now = ctx.get("now", time.time())
        kept = []
        for cmd in commands:
            fam = family_of(cmd)
            if fam in self.external:
                ctx_veto(ctx, cmd, "arbiter", f"'{fam}' is owned by an external controller")
            elif fam and self.yield_until.get(fam, 0) > now:
                ctx_veto(ctx, cmd, "arbiter",
                         f"external write to '{fam}' detected; yielding for "
                         f"{self.yield_until[fam] - now:.0f}s more")
            else:
                kept.append(cmd)
        return kept

    def on_sent(self, results, ctx):
        for r in results:
            fam = family_of(r["command"])
            val = s_value(r["command"])
            if r.get("ok") and fam in OBSERVED and val is not None:
                self.last_sent[fam] = (val, r.get("ts", ctx.get("now", time.time())))

    def tick(self, snap, ctx):
        now = ctx.get("now", time.time())
        for fam, key in OBSERVED.items():
            obs = snap.get(key)
            if obs is None:
                continue
            prev = self.prev_obs.get(fam)
            self.prev_obs[fam] = obs
            if prev is None or abs(obs - prev) < CHANGE_EPS:
                continue
            sent = self.last_sent.get(fam)
            ours = sent and abs(obs - sent[0]) <= MATCH_EPS and now - sent[1] <= GRACE_S
            if ours:
                continue
            self.yield_until[fam] = now + self.yield_s
            self.events.appendleft({
                "ts": now, "family": fam, "from": prev, "to": obs,
                "detail": f"external write: {key} {prev} -> {obs}; yielding {self.yield_s:.0f}s"})

    def status(self):
        now = time.time()
        return {
            "external_owned": sorted(self.external),
            "yielding": {f: round(t - now, 1) for f, t in self.yield_until.items() if t > now},
            "events": list(self.events),
        }


arbiter = Arbiter()


def register_hooks(hooks) -> None:
    hooks.on("commands.filter", arbiter.filter, priority=10)
    hooks.on("commands.sent", arbiter.on_sent, priority=10)
    hooks.on("tick", arbiter.tick, priority=10)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_arbiter", __name__, url_prefix="/api/v1/plugins/arbiter")

    @bp.route("", methods=["GET"])
    def arbiter_status():
        return jsonify(arbiter.status())

    app.register_blueprint(bp)
