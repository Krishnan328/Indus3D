"""
plugins/watchdog.py  (B3)
--------------------------
Kill-switch for the closed loop. If the auto-pilot misbehaves the watchdog
turns it OFF (state persisted, like the dashboard toggle), notifies, and blocks
further corrections until a human re-enables it. It trips on:

* rate        more than INDUS3D_WATCHDOG_MAX_PER_MIN commands in 60 s (default 60)
* oscillation >= INDUS3D_WATCHDOG_MAX_REVERSALS direction reversals of one
              value (flow / speed / nozzle temp) within 120 s (default 8)
* send errors INDUS3D_WATCHDOG_MAX_FAILS consecutive failed sends (default 5)

Re-arming is explicit: switching the auto-pilot back on clears the trip, as
does POST /api/v1/plugins/watchdog/reset (which does not re-enable it).

It does not judge print quality; it only guards against the controller itself
running away. GET /api/v1/plugins/watchdog shows state and recent trips.
"""

import logging
import os
import time
from collections import defaultdict, deque

from core.plugin_hooks import ctx_veto
from plugins.arbiter import family_of, s_value

PLUGIN_INFO = {
    "title": "Auto-pilot watchdog",
    "description": "Disables the auto-pilot if it runs away: too many commands, oscillation, or repeated send failures.",
}

RATE_WINDOW_S = 60.0
OSC_WINDOW_S = 120.0
MIN_DELTA = {"flow": 1.0, "speed": 1.0, "nozzle_temp": 1.0}


def _env_num(name, default):
    try:
        return type(default)(os.environ.get(name, default))
    except ValueError:
        return default


class Watchdog:
    def __init__(self, max_per_min=None, max_reversals=None, max_fails=None):
        self.max_per_min = max_per_min if max_per_min is not None else _env_num("INDUS3D_WATCHDOG_MAX_PER_MIN", 60)
        self.max_reversals = max_reversals if max_reversals is not None else _env_num("INDUS3D_WATCHDOG_MAX_REVERSALS", 8)
        self.max_fails = max_fails if max_fails is not None else _env_num("INDUS3D_WATCHDOG_MAX_FAILS", 5)
        self.sent = deque()                      # command timestamps
        self.values = defaultdict(deque)         # family -> (t, value)
        self.fails = 0
        self.tripped = None                      # {"ts", "reason"} while tripped
        self.trips = deque(maxlen=50)
        self.prev_autopilot = None

    # control ---------------------------------------------------------------
    def reset(self):
        self.tripped = None
        self.sent.clear()
        self.values.clear()
        self.fails = 0

    def _trip(self, reason, now):
        self.tripped = {"ts": now, "reason": reason}
        self.trips.appendleft(dict(self.tripped))
        logging.error(f"🛑 Watchdog tripped: {reason} — auto-pilot disabled")
        try:
            from digital_twin.quality_controller import quality_controller
            quality_controller.auto_pilot = False
        except Exception as e:  # noqa: BLE001
            logging.error(f"watchdog: could not disable auto-pilot: {e}")
        try:
            from core.notifications import notify
            notify(f"🛑 Indus3D watchdog disabled the auto-pilot: {reason}")
        except Exception:  # noqa: BLE001
            pass

    # hooks -----------------------------------------------------------------
    def filter(self, commands, ctx):
        if not self.tripped:
            return commands
        for cmd in commands:
            ctx_veto(ctx, cmd, "watchdog", f"tripped: {self.tripped['reason']}")
        return []

    def on_sent(self, results, ctx):
        now = ctx.get("now", time.time())
        for r in results:
            if not r.get("ok"):
                self.fails += 1
                continue
            self.fails = 0
            self.sent.append(r.get("ts", now))
            fam, val = family_of(r["command"]), s_value(r["command"])
            if fam in MIN_DELTA and val is not None:
                self.values[fam].append((r.get("ts", now), val))
        if self.tripped:
            return

        while self.sent and now - self.sent[0] > RATE_WINDOW_S:
            self.sent.popleft()
        if len(self.sent) > self.max_per_min:
            return self._trip(f"{len(self.sent)} commands in {RATE_WINDOW_S:.0f}s (limit {self.max_per_min})", now)
        if self.fails >= self.max_fails:
            return self._trip(f"{self.fails} consecutive failed sends", now)
        for fam, dq in self.values.items():
            while dq and now - dq[0][0] > OSC_WINDOW_S:
                dq.popleft()
            rev = self._reversals(fam, dq)
            if rev >= self.max_reversals:
                return self._trip(f"'{fam}' reversed direction {rev}x in {OSC_WINDOW_S:.0f}s (oscillation)", now)

    @staticmethod
    def _reversals(fam, dq) -> int:
        vals = [v for _, v in dq]
        last_sign, rev = 0, 0
        for a, b in zip(vals, vals[1:]):
            d = b - a
            if abs(d) < MIN_DELTA[fam]:
                continue
            sign = 1 if d > 0 else -1
            if last_sign and sign != last_sign:
                rev += 1
            last_sign = sign
        return rev

    def tick(self, snap, ctx):
        # Re-arm when a human turns the auto-pilot back on after a trip.
        try:
            from digital_twin.quality_controller import quality_controller
            ap = bool(quality_controller.auto_pilot)
        except Exception:  # noqa: BLE001
            return
        if self.tripped and ap and self.prev_autopilot is False:
            logging.info("🟢 Watchdog re-armed: auto-pilot re-enabled by user")
            self.reset()
        self.prev_autopilot = ap

    def status(self):
        return {
            "tripped": self.tripped,
            "limits": {"max_commands_per_min": self.max_per_min, "max_reversals": self.max_reversals,
                       "max_consecutive_failures": self.max_fails},
            "recent_commands_60s": len(self.sent),
            "consecutive_failures": self.fails,
            "trips": list(self.trips),
        }


watchdog = Watchdog()


def register_hooks(hooks) -> None:
    hooks.on("commands.filter", watchdog.filter, priority=20)
    hooks.on("commands.sent", watchdog.on_sent, priority=20)
    hooks.on("tick", watchdog.tick, priority=20)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_watchdog", __name__, url_prefix="/api/v1/plugins/watchdog")

    @bp.route("", methods=["GET"])
    def watchdog_status():
        return jsonify(watchdog.status())

    @bp.route("/reset", methods=["POST"])
    def watchdog_reset():
        watchdog.reset()
        return jsonify(watchdog.status())

    app.register_blueprint(bp)
