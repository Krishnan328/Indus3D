"""Typed toolhead / thermal controls: POST /api/v1/printer/adjust/<control>.

The browser never sends G-code for these controls. Each endpoint validates its numbers (bounded, finite,
never bool) and its object names (``moonraker_util.valid_name``: only names Klipper really has, matched
against a strict character set as well) and then builds the G-code itself. Nothing here grows the
``_SAFE_PREFIXES`` allowlist of the free-form console.

Common behaviour
* 400 for a bad request, 404 for an object Klipper does not have, 409 when the control makes no sense right
  now (print active, cold extruder, capability missing), 422 when Klipper rejects the script,
  502 when Moonraker is down.
* With the simulator running the script goes to ``workers._active_worker.inject_gcode`` instead.
* A successful manual change of flow, speed, pa, nozzle_temp, bed_temp, fan, z_offset or retraction is
  reported to ``plugins.arbiter.note_manual_change`` so the quality controller yields that family instead
  of overwriting the change seconds later.

Endpoints
  POST /heater            {heater, target}                       SET_HEATER_TEMPERATURE
  POST /fan               {fan, speed 0-1}                       M106/M107 or SET_FAN_SPEED
  POST /output_pin        {pin, value 0-1}                       SET_PIN
  POST /speed             {factor 10-300}                        M220
  POST /flow              {factor 10-300}                        M221
  POST /pressure_advance  {advance, smooth_time?}                SET_PRESSURE_ADVANCE
  POST /retraction        {retract_length?, ...}                 SET_RETRACTION (firmware_retraction only)
  POST /babystep          {step ±0.5}                            SET_GCODE_OFFSET Z_ADJUST=.. MOVE=1
  POST /save_z_offset     {target: probe|endstop, confirmed}     Z_OFFSET_APPLY_PROBE / _ENDSTOP
  POST /motors_off                                               M84
  POST /level             {action [, z]}                         leveling / probing enum
  POST /extrude           {amount ±100, feedrate?}               relative E move, cold-extrusion checked
"""

import math
import re
import time
from typing import List, Optional, Tuple

from flask import Blueprint, jsonify, request

from api import moonraker_util as mu
from config.settings import settings

adjust_bp = Blueprint("adjust", __name__)

TEMP_MARGIN_C = 5.0                                   # a setpoint must stay this far under the configured max_temp
SIM_LIMITS = {"extruder": 300.0, "heater_bed": 130.0, "heater_generic": 100.0}   # the simulator has no configfile
FACTOR_RANGE = (10.0, 300.0)
PA_RANGE = (0.0, 2.0)
PA_SMOOTH_RANGE = (0.0, 0.2)
BABYSTEP_MAX = 0.5
EXTRUDE_MAX_MM = 100.0
EXTRUDE_FEED_RANGE = (30.0, 3000.0)                   # mm/min, same unit as /api/v1/control/jog
TESTZ_MAX = 5.0
RETRACTION_RANGES = {
    "retract_length": (0.0, 20.0), "retract_speed": (1.0, 200.0),
    "unretract_extra_length": (-5.0, 5.0), "unretract_speed": (1.0, 200.0),
}
LEVEL_ACTIONS = {                                     # action -> capability that must exist (None = see _MANUAL_DIALOG)
    "Z_TILT_ADJUST": "z_tilt", "QUAD_GANTRY_LEVEL": "quad_gantry_level",
    "SCREWS_TILT_CALCULATE": "screws_tilt_adjust", "BED_SCREWS_ADJUST": "bed_screws",
    "PROBE_CALIBRATE": "probe",
    "TESTZ": None, "ACCEPT": None, "ABORT": None, "ADJUSTED": None,
}
_MANUAL_DIALOG = ("manual_probe", "probe", "bltouch", "bed_screws", "screws_tilt_adjust")

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_]{1,48}$")
_HEATER_FAMILY = re.compile(r"^(extruder\d*|heater_bed|heater_generic [A-Za-z0-9_]{1,48})$")


class Reject(Exception):
    """Turn into a JSON error response."""

    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


@adjust_bp.errorhandler(Reject)
def _reject(e: Reject):
    return jsonify({"error": e.message, **e.extra}), e.status


@adjust_bp.errorhandler(mu.MoonrakerError)
def _moonraker_down(e):
    return jsonify({"error": str(e), "moonraker": settings.moonraker_url}), 502


# ── helpers ───────────────────────────────────────────────────────────────────
def _body() -> dict:
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        raise Reject("JSON object expected")
    return data


def _sim():
    import workers
    w = workers._active_worker
    return w if workers.is_simulator(w) else None


def _busy() -> bool:
    from api.routes import printer
    return bool(printer._printer_is_busy())             # looked up at call time so tests can stub it


def _no_print(what: str) -> None:
    if _busy():
        raise Reject(f"{what} is disabled while a print is active", 409, print_active=True)


def _num(data: dict, key: str, lo: float, hi: float, required: bool = True) -> Optional[float]:
    value = data.get(key)
    if value is None:
        if required:
            raise Reject(f"{key} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Reject(f"{key} must be a number")
    if not lo <= value <= hi:
        raise Reject(f"{key} must be between {lo:g} and {hi:g}")
    return float(value)


def _fmt(value: float, places: int = 3) -> str:
    text = f"{value:.{places}f}"
    if "." in text:                                    # never strip the zeros of a whole number ("120" is not "12")
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _find_object(name, families: Tuple[str, ...]) -> str:
    """Canonical Klipper object name for ``name`` ('extruder', 'fan_generic exhaust', ...). In the simulator,
    which has no object list, the (pattern-checked) name is trusted. 404 when Klipper does not have it."""
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise Reject("object name is required")
    name = " ".join(name.split())
    head, _, rest = name.partition(" ")
    if head not in families:
        raise Reject(f"{name!r} is not one of: {', '.join(families)}", 400)
    if rest and not _SAFE_NAME.match(rest):
        raise Reject("invalid object name")
    if _sim():
        return name
    if not rest:
        low = name.lower()
        for obj in mu.list_objects():
            if obj.lower() == low:
                return obj
        raise Reject(f"Klipper has no object named {name!r}", 404)
    canonical = mu.valid_name(head, rest)
    if canonical is None:
        raise Reject(f"Klipper has no {head} named {rest!r}", 404)
    if not _SAFE_NAME.match(canonical):
        raise Reject(f"{head} {canonical!r} has a name that cannot be controlled from here", 400)
    return f"{head} {canonical}"


def _capabilities() -> set:
    return set(mu.list_objects())


def _send(lines: List[str], family: Optional[str] = None, detail: str = "", **extra):
    script = "\n".join(lines)
    w = _sim()
    if w:
        w.inject_gcode(script)
        body = {"status": "queued", "simulated": True}
    else:
        res = mu.run_script(script)
        if not res.ok:
            return jsonify({"status": "error", "detail": (res.text or "")[:300]}), 422
        live = _live_worker()
        if live is not None and hasattr(live, "live_commands"):
            for line in lines:
                live.live_commands.append({"text": f"[INDUS] {line}", "ts": time.time()})
        body = {"status": "ok", "simulated": False}
    if family:
        from plugins import arbiter
        arbiter.note_manual_change(family, detail=detail or f"manual {family} change from the UI")
    body.update(extra)
    return jsonify(body)


def _live_worker():
    import workers
    return workers._active_worker


# ── heaters ───────────────────────────────────────────────────────────────────
def _limit_for(canonical: str) -> float:
    if _sim():
        key = "heater_generic" if canonical.startswith("heater_generic") else \
              ("heater_bed" if canonical == "heater_bed" else "extruder")
        return SIM_LIMITS[key] - TEMP_MARGIN_C
    limits = mu.heater_limits()
    entry = limits.get(canonical.lower())
    if not entry:
        raise Reject(f"The configured max_temp of {canonical} is unknown, so no setpoint is accepted", 409)
    return entry["max_temp"] - TEMP_MARGIN_C


@adjust_bp.route("/heater", methods=["POST"])
def heater():
    data = _body()
    name = data.get("heater")
    clean = " ".join(name.split()) if isinstance(name, str) else ""
    if not _HEATER_FAMILY.match(clean):
        raise Reject("heater must be extruder, extruderN, heater_bed or heater_generic <name>")
    canonical = _find_object(clean, (clean.split(" ")[0],))
    ceiling = _limit_for(canonical)
    target = _num(data, "target", 0, max(ceiling, 0))
    klipper_name = canonical.split(" ", 1)[1] if canonical.startswith("heater_generic ") else canonical
    family = "nozzle_temp" if canonical.startswith("extruder") else ("bed_temp" if canonical == "heater_bed" else None)
    return _send([f"SET_HEATER_TEMPERATURE HEATER={klipper_name} TARGET={_fmt(target, 1)}"], family,
                 f"{canonical} target set to {_fmt(target, 1)}°C", heater=canonical, target=target, max_target=ceiling)


# ── fans and outputs ──────────────────────────────────────────────────────────
@adjust_bp.route("/fan", methods=["POST"])
def fan():
    data = _body()
    name = data.get("fan", "fan")
    speed = _num(data, "speed", 0, 1)
    canonical = _find_object(name, ("fan", "fan_generic"))
    if canonical == "fan":
        lines = ["M107"] if speed == 0 else [f"M106 S{round(speed * 255)}"]
    else:
        lines = [f"SET_FAN_SPEED FAN={canonical.split(' ', 1)[1]} SPEED={_fmt(speed)}"]
    return _send(lines, "fan", f"{canonical} set to {round(speed * 100)}%", fan=canonical, speed=speed)


@adjust_bp.route("/output_pin", methods=["POST"])
def output_pin():
    data = _body()
    canonical = _find_object(data.get("pin"), ("output_pin",))
    value = _num(data, "value", 0, 1)
    return _send([f"SET_PIN PIN={canonical.split(' ', 1)[1]} VALUE={_fmt(value)}"], None,
                 pin=canonical, value=value)


# ── speed, flow, pressure advance, retraction ─────────────────────────────────
@adjust_bp.route("/speed", methods=["POST"])
def speed():
    factor = _num(_body(), "factor", *FACTOR_RANGE)
    return _send([f"M220 S{_fmt(factor, 0)}"], "speed", f"speed factor set to {_fmt(factor, 0)}%", factor=factor)


@adjust_bp.route("/flow", methods=["POST"])
def flow():
    factor = _num(_body(), "factor", *FACTOR_RANGE)
    return _send([f"M221 S{_fmt(factor, 0)}"], "flow", f"flow factor set to {_fmt(factor, 0)}%", factor=factor)


@adjust_bp.route("/pressure_advance", methods=["POST"])
def pressure_advance():
    data = _body()
    advance = _num(data, "advance", *PA_RANGE)
    smooth = _num(data, "smooth_time", *PA_SMOOTH_RANGE, required=False)
    line = f"SET_PRESSURE_ADVANCE ADVANCE={_fmt(advance, 4)}"
    if smooth is not None:
        line += f" SMOOTH_TIME={_fmt(smooth, 4)}"
    return _send([line], "pa", f"pressure advance set to {_fmt(advance, 4)}", advance=advance, smooth_time=smooth)


@adjust_bp.route("/retraction", methods=["POST"])
def retraction():
    data = _body()
    parts = []
    for key, (lo, hi) in RETRACTION_RANGES.items():
        value = _num(data, key, lo, hi, required=False)
        if value is not None:
            parts.append(f"{key.upper()}={_fmt(value)}")
    if not parts:
        raise Reject("give at least one of: " + ", ".join(RETRACTION_RANGES))
    if not _sim() and "firmware_retraction" not in _capabilities():
        raise Reject("Klipper has no [firmware_retraction] section", 409)
    return _send(["SET_RETRACTION " + " ".join(parts)], "retraction", "firmware retraction changed")


# ── Z offset ──────────────────────────────────────────────────────────────────
@adjust_bp.route("/babystep", methods=["POST"])
def babystep():
    step = _num(_body(), "step", -BABYSTEP_MAX, BABYSTEP_MAX)
    if step == 0:
        raise Reject("step must not be zero")
    return _send([f"SET_GCODE_OFFSET Z_ADJUST={_fmt(step)} MOVE=1"], "z_offset",
                 f"Z babystep {_fmt(step)} mm", step=step)


@adjust_bp.route("/save_z_offset", methods=["POST"])
def save_z_offset():
    data = _body()
    target = data.get("target")
    if target not in ("probe", "endstop"):
        raise Reject("target must be 'probe' or 'endstop'")
    if data.get("confirmed") is not True:
        raise Reject("Saving the Z offset rewrites the printer configuration: confirm first", 409,
                     needs_confirmation=True)
    if target == "probe" and not _sim() and not ({"probe", "bltouch"} & _capabilities()):
        raise Reject("Klipper has no probe to save the offset to; use target 'endstop'", 409)
    cmd = "Z_OFFSET_APPLY_PROBE" if target == "probe" else "Z_OFFSET_APPLY_ENDSTOP"
    return _send([cmd], "z_offset", f"Z offset saved to {target}", target=target, restart_required=True,
                 message="The new offset is staged. Run SAVE_CONFIG (the printer restarts) to make it permanent.")


# ── motors, leveling, extrusion ───────────────────────────────────────────────
@adjust_bp.route("/motors_off", methods=["POST"])
def motors_off():
    _no_print("Turning the motors off")
    return _send(["M84"])


@adjust_bp.route("/level", methods=["POST"])
def level():
    data = _body()
    action = data.get("action")
    if not isinstance(action, str) or action.upper() not in LEVEL_ACTIONS:
        raise Reject("action must be one of: " + ", ".join(LEVEL_ACTIONS))
    action = action.upper()
    _no_print("Leveling and probing")
    if not _sim():
        have = _capabilities()
        needed = LEVEL_ACTIONS[action]
        if needed == "probe":
            ok = bool({"probe", "bltouch"} & have)
        elif needed is None:
            ok = bool(set(_MANUAL_DIALOG) & have)
        else:
            ok = needed in have
        if not ok:
            raise Reject(f"This printer has no {needed or 'manual probe'} support, so {action} is not available", 409)
    line = action
    if action == "TESTZ":
        raw = data.get("z")
        if isinstance(raw, str) and raw in ("+", "-", "++", "--"):   # Klipper's coarse/fine shorthand
            line = f"TESTZ Z={raw}"
        else:
            line = f"TESTZ Z={_fmt(_num(data, 'z', -TESTZ_MAX, TESTZ_MAX))}"
    return _send([line], None, action=action)


@adjust_bp.route("/extrude", methods=["POST"])
def extrude():
    data = _body()
    _no_print("Extruding and retracting")
    amount = _num(data, "amount", -EXTRUDE_MAX_MM, EXTRUDE_MAX_MM)
    if amount == 0:
        raise Reject("amount must not be zero")
    feed = _num({"feedrate": data.get("feedrate", 300)}, "feedrate", *EXTRUDE_FEED_RANGE)
    if not _sim():
        status = mu.query_objects(["extruder"]).get("extruder", {})
        if status.get("can_extrude") is not True:
            raise Reject("The extruder is below its minimum extrusion temperature: heat it first", 409, cold=True)
    return _send(["SAVE_GCODE_STATE NAME=INDUS_EXTRUDE", "M83", f"G1 E{_fmt(amount)} F{_fmt(feed, 0)}",
                  "RESTORE_GCODE_STATE NAME=INDUS_EXTRUDE"], None, amount=amount, feedrate=feed)
