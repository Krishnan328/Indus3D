"""
plugins/thermal_sanity.py  (B4)
--------------------------------
Early warnings that a heater or thermistor is going bad, beyond Klipper's own
runaway protection. Warn-only: it notifies and records events, it never sends
G-code or stops a print.

Checks (per heater, evaluated every telemetry tick):
* sensor_spike      reading jumps > SPIKE_C between consecutive ticks
                    (loose thermistor / noisy wiring)
* off_target        while printing, more than OFF_TARGET_C from the target for
                    OFF_TARGET_S seconds (PID drift, draught, weak heater)
* heater_not_heating (hotend, which reports PWM) PWM >= 95 % for
                    NO_RESPONSE_S seconds with < 1 °C rise while below target
                    (failed cartridge, loose heater connector)

Each (heater, kind) fires once and re-arms after the condition has been clear
for 30 s.  GET /api/v1/plugins/thermal_sanity
"""

import logging
from collections import deque

PLUGIN_INFO = {
    "title": "Thermal sanity",
    "description": "Warns about failing heaters/thermistors: spikes, drift, heaters that do not heat.",
}

SPIKE_C = 15.0
OFF_TARGET_C = 10.0
OFF_TARGET_S = 90.0
NO_RESPONSE_S = 20.0
CLEAR_S = 30.0
MAX_DT = 2.0   # ticks further apart than this (stalls) are not treated as a spike


class ThermalSanity:
    HEATERS = {
        "hotend": ("ext_temp", "ext_target", "ext_pwm"),
        "bed": ("bed_temp", "bed_target", None),
    }

    def __init__(self, notify=None):
        self.notify = notify
        self.prev = {}          # heater -> (t, temp)
        self.cond_since = {}    # (heater, kind) -> t the condition began
        self.clear_since = {}   # (heater, kind) -> t it stopped holding
        self.active = {}        # (heater, kind) -> event dict (currently raised)
        self.window = {}        # heater -> deque[(t, temp)] while PWM saturated
        self.events = deque(maxlen=100)
        self.total = 0

    def _raise(self, heater, kind, now, detail):
        key = (heater, kind)
        if key in self.active:
            return
        ev = {"ts": now, "heater": heater, "kind": kind, "detail": detail}
        self.active[key] = ev
        self.events.appendleft(ev)
        self.total += 1
        logging.warning(f"🌡️  thermal_sanity: {heater} {kind}: {detail}")
        if self.notify:
            try:
                self.notify(f"🌡️ Indus3D thermal sanity — {heater}: {detail}")
            except Exception:  # noqa: BLE001
                pass

    def _hold(self, key, holds, now, duration):
        """True once ``holds`` has been continuously true for ``duration`` s."""
        if holds:
            self.clear_since.pop(key, None)
            start = self.cond_since.setdefault(key, now)
            return now - start >= duration
        self.cond_since.pop(key, None)
        if key in self.active:
            start = self.clear_since.setdefault(key, now)
            if now - start >= CLEAR_S:
                self.active.pop(key, None)
                self.clear_since.pop(key, None)
        return False

    def tick(self, snap, ctx):
        now = ctx.get("now")
        printing = snap.get("print_state") == "printing"
        for heater, (tk, gk, pk) in self.HEATERS.items():
            temp, target = snap.get(tk), snap.get(gk)
            if temp is None:
                continue
            pwm = snap.get(pk) if pk else None

            prev = self.prev.get(heater)
            self.prev[heater] = (now, temp)
            # The simulator teleports temperatures; that is not a failing sensor.
            spike = bool(prev and ctx.get("source") != "sim"
                         and 0 < now - prev[0] <= MAX_DT and abs(temp - prev[1]) > SPIKE_C)
            if spike:
                self._raise(heater, "sensor_spike", now, f"reading jumped {prev[1]:.1f} -> {temp:.1f} °C in one tick")
            self._hold((heater, "sensor_spike"), spike, now, 0)

            off = bool(printing and target and abs(temp - target) > OFF_TARGET_C)
            if self._hold((heater, "off_target"), off, now, OFF_TARGET_S):
                self._raise(heater, "off_target", now,
                            f"{temp:.1f} °C vs target {target:.1f} °C for over {OFF_TARGET_S:.0f}s")

            if pwm is not None:
                w = self.window.setdefault(heater, deque())
                saturated = bool(target and pwm >= 0.95 and temp < target - 5)
                if saturated:
                    w.append((now, temp))
                else:
                    w.clear()
                stuck = bool(w and now - w[0][0] >= NO_RESPONSE_S
                             and (max(t for _, t in w) - w[0][1]) < 1.0)
                if stuck:
                    self._raise(heater, "heater_not_heating", now,
                                f"PWM {pwm:.0%} for {NO_RESPONSE_S:.0f}s with <1 °C rise "
                                f"(at {temp:.1f} °C, target {target:.1f})")
                self._hold((heater, "heater_not_heating"), saturated, now, 0)   # re-arm bookkeeping

    def status(self):
        return {"raised": [dict(e) for e in self.active.values()], "events": list(self.events),
                "total_events": self.total}


def _notify(msg):
    from core.notifications import notify
    notify(msg)


sanity = ThermalSanity(notify=_notify)


def register_hooks(hooks) -> None:
    hooks.on("tick", sanity.tick, priority=40)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_thermal_sanity", __name__, url_prefix="/api/v1/plugins/thermal_sanity")

    @bp.route("", methods=["GET"])
    def sanity_status():
        return jsonify(sanity.status())

    app.register_blueprint(bp)
