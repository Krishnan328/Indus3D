"""
plugins/prometheus_exporter.py  (E3)
-------------------------------------
GET /metrics in the Prometheus text format (0.0.4), for Grafana dashboards and
long-term trends.

Authentication: /metrics sits behind Indus3D's normal auth gate. When
INDUS3D_PASSWORD is set, configure Prometheus with
``authorization: {type: Bearer, credentials: <password>}``.

What is exported
  indus3d_up, indus3d_autopilot_enabled, indus3d_print_state{state}
  every numeric field of the live telemetry (temperatures, progress, velocity,
  speed/flow factors, power, disk, vibration, kinematics, thermals, extrusion),
  named indus3d_<section>_<field> (nested dicts are flattened)
  indus3d_quality_<field> for the controller's active values
  indus3d_commands_total{family,result}, indus3d_vetoes_total{plugin},
  indus3d_shadow_commands_total{family}
  plugin state: watchdog trip, arbiter yields, approval queue, thermal events,
  first-layer blocks, print health score, filament-sensor reading
"""

import math
import re
import threading
from collections import Counter

from plugins.arbiter import family_of

PLUGIN_INFO = {
    "title": "Prometheus exporter",
    "description": "Exposes telemetry, controller activity and plugin state at /metrics.",
}

SECTIONS = ("power", "disk", "vibration", "kinematics", "thermals", "extrusion")
_BAD = re.compile(r"[^a-zA-Z0-9_]")

_lock = threading.Lock()
_commands = Counter()   # (family, result)
_vetoes = Counter()     # plugin
_shadow = Counter()     # family


def _name(*parts) -> str:
    n = _BAD.sub("_", "_".join(str(p) for p in parts)).strip("_").lower()
    return "indus3d_" + (n if not n[:1].isdigit() else "_" + n)


def _label(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _flatten(prefix, obj, out, depth=0):
    if isinstance(obj, bool):
        out.append((prefix, float(obj)))
    elif isinstance(obj, (int, float)):
        if math.isfinite(obj):
            out.append((prefix, float(obj)))
    elif isinstance(obj, dict) and depth < 2:
        for k, v in obj.items():
            _flatten(f"{prefix}_{k}", v, out, depth + 1)


class Exposition:
    def __init__(self):
        self.lines, self._typed, self._seen = [], set(), set()

    def add(self, name, value, labels=None, help_="", type_="gauge"):
        series = (name, tuple(sorted((labels or {}).items())))
        if series in self._seen:          # a duplicate series makes the page invalid
            return
        self._seen.add(series)
        if name not in self._typed:
            self._typed.add(name)
            if help_:
                self.lines.append(f"# HELP {name} {help_}")
            self.lines.append(f"# TYPE {name} {type_}")
        lab = "{" + ",".join(f'{k}="{_label(v)}"' for k, v in labels.items()) + "}" if labels else ""
        self.lines.append(f"{name}{lab} {value:g}")

    def text(self):
        return "\n".join(self.lines) + "\n"


def render(latest: dict, autopilot=None, quality=None, plugin_state=None) -> str:
    x = Exposition()
    latest = latest or {}
    x.add("indus3d_up", 1.0 if latest.get("online") or latest.get("sim") else 0.0,
          help_="1 when the printer link (or simulator) is up")
    if autopilot is not None:
        x.add("indus3d_autopilot_enabled", float(bool(autopilot)))
    x.add("indus3d_print_state", 1.0, {"state": latest.get("print_state", "unknown")})

    flat = []
    for k, v in latest.items():
        if k in SECTIONS:
            _flatten(f"{k}", v, flat)
        elif k not in ("quality", "live_commands", "notifications", "exclude_object"):
            _flatten(k, v, flat)
    for k, v in flat:
        x.add(_name(k), v)

    for k, v in (quality or {}).items():
        if isinstance(v, bool) or isinstance(v, (int, float)):
            x.add(_name("quality", k), float(v))
        elif k == "nozzle_status":
            x.add("indus3d_quality_nozzle_status", 1.0, {"status": v})

    with _lock:
        for (fam, res), n in sorted(_commands.items()):
            x.add("indus3d_commands_total", n, {"family": fam, "result": res},
                  "Corrective commands by family and result", "counter")
        for plugin, n in sorted(_vetoes.items()):
            x.add("indus3d_vetoes_total", n, {"plugin": plugin}, "Commands dropped by a plugin", "counter")
        for fam, n in sorted(_shadow.items()):
            x.add("indus3d_shadow_commands_total", n, {"family": fam},
                  "Commands the controller would have sent (auto-pilot off)", "counter")

    for name, value, labels in (plugin_state or []):
        x.add(name, value, labels)
    return x.text()


# hooks ----------------------------------------------------------------------
def on_sent(results, ctx):
    with _lock:
        for r in results:
            _commands[(family_of(r["command"]) or "other", "ok" if r.get("ok") else "failed")] += 1


def on_vetoed(vetoes, ctx):
    with _lock:
        for v in vetoes:
            _vetoes[v["plugin"]] += 1


def on_shadow(commands, ctx):
    with _lock:
        for c in commands:
            _shadow[family_of(c) or "other"] += 1


def _plugin_state():
    import time
    out = []
    try:
        from plugins.watchdog import watchdog
        out.append(("indus3d_watchdog_tripped", float(bool(watchdog.tripped)), None))
        out.append(("indus3d_watchdog_commands_60s", float(len(watchdog.sent)), None))
    except Exception:  # noqa: BLE001
        pass
    try:
        from plugins.arbiter import arbiter
        now = time.time()
        for fam, until in arbiter.yield_until.items():
            out.append(("indus3d_arbiter_yield_seconds", max(0.0, until - now), {"family": fam}))
    except Exception:  # noqa: BLE001
        pass
    try:
        from plugins.approval import approval
        out.append(("indus3d_approval_enabled", float(approval.enabled), None))
        out.append(("indus3d_approval_pending", float(len(approval.pending)), None))
    except Exception:  # noqa: BLE001
        pass
    try:
        from plugins.thermal_sanity import sanity
        out.append(("indus3d_thermal_sanity_events_total", float(sanity.total), None))
    except Exception:  # noqa: BLE001
        pass
    try:
        from plugins.first_layer_guard import guard
        out.append(("indus3d_first_layer_blocked_total", float(guard.blocked_total), None))
    except Exception:  # noqa: BLE001
        pass
    try:
        from plugins.health_score import health
        score = (health.score()["score"] if health.printing
                 else (health.last_final or {}).get("score"))
        if score is not None:
            out.append(("indus3d_print_health_score", float(score), None))
    except Exception:  # noqa: BLE001
        pass
    try:
        from plugins.filament_sensor import bridge
        s = bridge.summary()
        out.append(("indus3d_filament_sensor_connected", float(s["connected"]), None))
        for key in ("diameter_mm", "spool_remaining_g"):
            if isinstance(s.get(key), (int, float)):
                out.append((f"indus3d_filament_sensor_{key}", float(s[key]), None))
    except Exception:  # noqa: BLE001
        pass
    return out


def register_hooks(hooks) -> None:
    hooks.on("commands.sent", on_sent, priority=95)
    hooks.on("commands.vetoed", on_vetoed, priority=95)
    hooks.on("shadow.commands", on_shadow, priority=95)


def register_routes(app) -> None:
    from flask import Response

    @app.route("/metrics", methods=["GET"], endpoint="plugin_prometheus_metrics")
    def metrics():
        import workers
        from digital_twin.quality_controller import quality_controller as qc
        w = workers._active_worker
        body = render(w.latest if w else {}, qc.auto_pilot, qc.active, _plugin_state())
        return Response(body, mimetype="text/plain; version=0.0.4")
