"""
plugins/filament_sensor.py  (C1)
---------------------------------
Integration with the smart filament sensor host daemon (helpers/filament_sensor,
REST on 127.0.0.1:7126). A background thread polls its /status (never the
telemetry thread). What Indus3D does with it:

* Visibility   latest reading + derived summary at GET …/filament_sensor, shown
               on the dashboard card, exported to /metrics.
* Alerts       a notification AND an action_log entry (alert_id
               "filament_sensor:<kind>") on a sensor fault, filament leaving the
               sensor mid-print, a runout countdown, and when the daemon starts
               writing M221 — so the daemon's own pauses are visible in the audit
               trail, not just in Klipper's console.
* Arbiter      while the daemon's auto-flow is active, flow is declared
               externally owned so Indus3D's flow loop yields instead of fighting it.
* Controller   adds measured values to the controller's inputs:
                 ext["sensor_flow_mm3_s"]   speed × area of the diameter that is at
                                            the NOZZLE now (the daemon delays the
                                            reading by the Bowden length)
                 ext["sensor_diameter_mm"], ext["sensor_flow_ratio"]
               and, only if INDUS3D_SENSOR_FLOW_INPUT=1, replaces the estimated
               ext["flow_ratio"] with the measured one. Use that with the daemon's
               auto-flow DISABLED (enable_auto_flow = false): two loops must not
               both correct M221. It is skipped automatically while the daemon owns flow.
* Spool        after each print, replaces the estimated filament use in
               print_history (and the virtual spool and cost) with the sensor's
               measured grams, when both ends of the print were observed and the
               figures are plausible. Logged to action_log. INDUS3D_SENSOR_SPOOL_SYNC=0 turns it off.
* Actions      tare / span calibration / reset spool / reset Bowden buffer, proxied
               through Indus3D's authenticated API (the daemon itself is bound to
               localhost). Refused during a print and require "confirmed": true.

INDUS3D_SENSOR_URL   default http://127.0.0.1:7126 ; set empty to disable
INDUS3D_SENSOR_INI   optional path to indus3d_sensor.ini (declares auto-flow)

GET  /api/v1/plugins/filament_sensor
POST /api/v1/plugins/filament_sensor/action
     {"action": "tare_empty|calibrate_span|reset_spool|reset_bowden", "target": 1.75, "confirmed": true}
"""

import configparser
import logging
import math
import os
import threading
import time
from collections import deque

from plugins._common import delayed, http_json

PLUGIN_INFO = {
    "title": "Filament sensor integration",
    "description": "Sensor data, alerts, measured flow for the controller, measured spool use, and calibration actions.",
}

# Keys of the daemon's /status that this plugin (and plugins reading bridge.summary()["raw"]) rely on.
# tests/test_sensor_contract.py checks them against the daemon source so the two cannot drift apart.
STATUS_KEYS_USED = (
    "connected", "faults", "filament_present", "diameter_mm", "velocity_mm_s", "volumetric_flow_mm3_s",
    "nozzle_diameter_mm", "auto_flow_percent", "runout_countdown_mm", "spool_used_g", "spool_remaining_g",
    "nominal_area_pct", "bed_jerk_mg",
)
ACTIONS = {
    "tare_empty": "/tare_empty",
    "calibrate_span": "/calibrate_span",
    "reset_spool": "/reset_spool",
    "reset_bowden": "/reset_bowden",
}

POLL_S = 2.0
FRESH_S = 3.0
AUTO_FLOW_HOLD_S = 120.0   # keep treating flow as externally owned this long after the last deviation
FLOW_EPS = 0.5
NOMINAL_DIA_MM = 1.75
MAX_RATIO = 3.0


def fetch_status(url: str, timeout: float = 1.0) -> dict:
    return http_json(url.rstrip("/") + "/status", timeout=timeout)


def ini_auto_flow(path):
    if not path or not os.path.isfile(path):
        return None
    cp = configparser.ConfigParser()
    cp.read(path)
    return cp.getboolean("features", "enable_auto_flow", fallback=False)


def nozzle_flow_mm3_s(status: dict):
    """Volumetric flow at the nozzle now: filament speed at the sensor × area of the
    diameter that left the sensor one Bowden length ago. None if unusable."""
    v, d = status.get("velocity_mm_s"), status.get("nozzle_diameter_mm")
    if not isinstance(v, (int, float)) or not isinstance(d, (int, float)) or d <= 0.5:
        return None
    return max(0.0, v) * math.pi * (d / 2.0) ** 2


def _audit(alert_id, description, status="observed", now=None):
    try:
        from db.models import get_connection
        conn = get_connection()
        try:
            conn.execute("INSERT INTO action_log (timestamp, alert_id, gcode, description, status) VALUES (?, ?, ?, ?, ?)",
                         (now or time.time(), alert_id, "", description, status))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logging.info(f"filament_sensor: audit write failed: {e}")


class SpoolSync:
    """Replaces the 3 g/m filament estimate with the sensor's measured grams after each print."""

    def __init__(self, enabled=None, db=None, price=None, audit=_audit):
        self.enabled = (os.environ.get("INDUS3D_SENSOR_SPOOL_SYNC", "1") != "0") if enabled is None else enabled
        self._conn = db
        self._price = price
        self._audit = audit
        self.start = None
        self.results = deque(maxlen=20)
        self._done = set()

    def _connect(self):
        if self._conn:
            return self._conn()
        from db.models import get_connection
        return get_connection()

    def _price_per_g(self):
        if self._price:
            return self._price()
        try:
            from services.spoolman_client import get_spool_price_per_g
            return float(get_spool_price_per_g() or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def begin(self, sensor_used_g, now=None):
        """Called when a print starts. ``sensor_used_g`` None = sensor not usable."""
        last_id = 0
        try:
            conn = self._connect()
            try:
                last_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM print_history").fetchone()[0]
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            pass
        self.start = {"used": sensor_used_g, "last_id": last_id, "t": now or time.time()}

    def finish(self, run, sensor_used_g, now=None):
        st, self.start = self.start, None
        res = {"run": run["id"], "filename": run.get("filename"), "applied": False, "ts": now or time.time()}
        if not self.enabled:
            res["reason"] = "disabled"
        elif run["id"] in self._done:
            res["reason"] = "already applied"
        elif not st or st["used"] is None or sensor_used_g is None:
            res["reason"] = "sensor not observed at both ends of the print"
        else:
            measured = round(sensor_used_g - st["used"], 2)
            if measured < 0.05:
                res["reason"] = f"no measurable filament use ({measured} g; spool counter reset mid-print?)"
            else:
                self._apply(run, st, measured, res)
        self.results.appendleft(res)
        return res

    def _apply(self, run, st, measured, res):
        try:
            conn = self._connect()
        except Exception as e:  # noqa: BLE001
            res["reason"] = f"database unavailable: {e}"
            return
        try:
            row = conn.execute("SELECT id, filament_used_g, cost_usd FROM print_history "
                               "WHERE id > ? AND filename = ? ORDER BY id DESC LIMIT 1",
                               (st["last_id"], run.get("filename"))).fetchone()
            if not row:
                res["reason"] = "no print_history row found for this print"
                return
            rid, est, cost = row[0], float(row[1] or 0.0), float(row[2] or 0.0)
            if est > 0 and not (0.2 * est <= measured <= 5.0 * est):
                res["reason"] = f"implausible: sensor {measured} g vs estimate {est:.1f} g"
                res["measured_g"], res["estimated_g"] = measured, round(est, 2)
                return
            price = self._price_per_g()
            conn.execute("UPDATE print_history SET filament_used_g = ?, cost_usd = ? WHERE id = ?",
                         (measured, max(0.0, cost + (measured - est) * price), rid))
            v = conn.execute("SELECT value FROM printer_config WHERE key = 'virtual_spool_used_g'").fetchone()
            if v is not None:
                conn.execute("INSERT OR REPLACE INTO printer_config (key, value) VALUES ('virtual_spool_used_g', ?)",
                             (str(max(0.0, float(v[0]) + (measured - est))),))
            conn.commit()
            res.update(applied=True, print_history_id=rid, measured_g=measured, estimated_g=round(est, 2))
            self._done.add(run["id"])
            self._audit("sensor_spool_sync",
                        f"print #{rid}: filament {est:.1f} g (estimate) -> {measured:.1f} g (measured by sensor)",
                        "applied")
        finally:
            conn.close()


class SensorBridge:
    def __init__(self, url=None, ini_path=None, notify=None, arbiter_external=None, audit=_audit, spool=None,
                 flow_input=None):
        self.url = os.environ.get("INDUS3D_SENSOR_URL", "http://127.0.0.1:7126") if url is None else url
        self.ini_path = os.environ.get("INDUS3D_SENSOR_INI", "") if ini_path is None else ini_path
        self.notify = notify
        self.external = arbiter_external if arbiter_external is not None else set()  # the arbiter's own set
        self._audit = audit
        self.spool = spool or SpoolSync(audit=audit)
        self.flow_input = (os.environ.get("INDUS3D_SENSOR_FLOW_INPUT", "0") == "1") if flow_input is None else flow_input
        self.status = None
        self.connected = False
        self.last_ok = None
        self.last_error = None
        self.auto_flow_seen_at = None
        self.owns_flow_flag = False
        self.alerted = set()
        self.events = deque(maxlen=50)
        self.print_state = None
        self.flow_input_state = "off" if not self.flow_input else "waiting"
        self._was_printing = False
        self._runout_active = False
        self._started = False
        self._lock = threading.Lock()

    # -- polling ---------------------------------------------------------------
    def poll_once(self, fetch=fetch_status, now=None):
        now = now if now is not None else time.time()
        try:
            data = fetch(self.url)
        except Exception as e:  # noqa: BLE001 — an absent sensor is normal (printer off)
            with self._lock:
                if self.connected:
                    logging.info(f"🧵 filament sensor daemon unreachable: {e}")
                self.connected, self.last_error = False, f"{type(e).__name__}: {e}"
            self._update_arbiter(now)
            return None
        with self._lock:
            self.status, self.connected, self.last_ok, self.last_error = data, True, now, None
        pct = data.get("auto_flow_percent")
        if isinstance(pct, (int, float)) and abs(pct - 100.0) > FLOW_EPS:
            if self.auto_flow_seen_at is None or now - self.auto_flow_seen_at > AUTO_FLOW_HOLD_S:
                self._event("auto_flow", f"daemon is correcting flow (M221 ≈ {pct:.1f} %)", now)
            self.auto_flow_seen_at = now
        self._update_arbiter(now)
        self._alerts(data, now)
        return data

    def _event(self, kind, detail, now, notify=False):
        self.events.appendleft({"ts": now, "kind": kind, "detail": detail})
        self._audit(f"filament_sensor:{kind}", detail, "observed", now)
        if notify and self.notify:
            try:
                self.notify(f"🧵 Indus3D: {detail}")
            except Exception:  # noqa: BLE001
                pass

    def _update_arbiter(self, now):
        declared = ini_auto_flow(self.ini_path)
        seen = self.auto_flow_seen_at is not None and now - self.auto_flow_seen_at <= AUTO_FLOW_HOLD_S
        want = bool(declared) or seen
        if want and "flow" not in self.external:
            self.external.add("flow")
            self.owns_flow_flag = True
            logging.info("🧵 filament sensor auto-flow is active: Indus3D flow loop will yield (M221)")
        elif not want and self.owns_flow_flag:
            self.external.discard("flow")
            self.owns_flow_flag = False

    def _alerts(self, data, now):
        faults = data.get("faults", "NORMAL")
        printing = self.print_state == "printing"
        countdown = data.get("runout_countdown_mm") or 0.0
        conds = (
            ("fault", faults not in ("NORMAL", None, ""), f"filament sensor fault: {faults}"),
            ("runout", printing and data.get("filament_present") is False,
             "filament left the sensor during a print"),
        )
        for key, cond, msg in conds:
            if cond and key not in self.alerted:
                self.alerted.add(key)
                self._event(key, msg, now, notify=True)
            elif not cond:
                self.alerted.discard(key)
        if countdown > 0 and not self._runout_active:
            self._runout_active = True
            self._event("runout_countdown", f"runout: {countdown:.0f} mm of filament left in the Bowden tube "
                                            "before the daemon pauses the print", now)
        elif countdown <= 0 and self._runout_active:
            self._runout_active = False
            if self.print_state in ("paused", "printing") and data.get("filament_present") is False:
                self._event("runout_pause", "Bowden buffer exhausted — the daemon triggers SMART_RUNOUT_PAUSE", now)

    # -- controller inputs -----------------------------------------------------
    def _fresh(self, now):
        return bool(self.connected and self.status and self.last_ok and now - self.last_ok <= FRESH_S
                    and self.status.get("filament_present", True))

    def inputs(self, snap, kin, thm, ext, ctx):
        now = ctx.get("now", time.time())
        if not self._fresh(now):
            if self.flow_input:
                self.flow_input_state = "idle: sensor not fresh/connected"
            return
        s = self.status
        flow = nozzle_flow_mm3_s(s)
        if flow is None:
            return
        ext["sensor_flow_mm3_s"] = round(flow, 4)
        ext["sensor_diameter_mm"] = s.get("nozzle_diameter_mm")
        expected = ext.get("expected_flow_mm3_s", 0.0)
        if not (expected and expected > 0.5 and ext.get("is_extruding")):
            if self.flow_input:
                self.flow_input_state = "idle: not extruding"
            return
        ratio = max(0.0, min(MAX_RATIO, flow / expected))
        ext["sensor_flow_ratio"] = round(ratio, 3)
        if not self.flow_input:
            return
        if self.owns_flow_flag:
            self.flow_input_state = "skipped: the daemon's auto-flow owns M221"
            return
        ext["flow_ratio_estimated"] = ext.get("flow_ratio")
        ext["flow_ratio"] = round(ratio, 3)
        ext["flow_ratio_source"] = "sensor"
        self.flow_input_state = "active"

    # -- print lifecycle (spool sync) ------------------------------------------
    def _used_g(self):
        s = self.status if self.connected else None
        v = (s or {}).get("spool_used_g")
        return float(v) if isinstance(v, (int, float)) else None

    def tick(self, snap, ctx):
        self.print_state = snap.get("print_state")
        printing = self.print_state == "printing"
        if printing and not self._was_printing:
            self.spool.begin(self._used_g(), ctx.get("now"))
        self._was_printing = printing
        if not self._started and self.url:
            self._started = True
            threading.Thread(target=self._loop, daemon=True, name="filament-sensor-poll").start()

    def on_run_finish(self, run):
        # print_history is written by the telemetry worker as the print ends; read it a few seconds later
        used_at_end = self._used_g()
        delayed(8.0, lambda: self.spool.finish(run, used_at_end))

    def _loop(self):
        while True:
            self.poll_once()
            time.sleep(POLL_S)

    # -- actions ---------------------------------------------------------------
    def run_action(self, action, target=None, confirmed=False, fetch=None, now=None):
        """Proxy a daemon control action. Returns (status_code, body)."""
        if action not in ACTIONS:
            return 400, {"error": f"unknown action '{action}' (known: {', '.join(ACTIONS)})"}
        if confirmed is not True:
            return 412, {"error": "explicit confirmation is required: send {'confirmed': true}"}
        if not self.url:
            return 503, {"error": "filament sensor integration is disabled (INDUS3D_SENSOR_URL is empty)"}
        if self.print_state in ("printing", "paused"):
            return 409, {"error": "refused during a print: calibrating or resetting would corrupt the measurement"}
        path = ACTIONS[action]
        if action == "calibrate_span":
            try:
                target = float(target if target is not None else NOMINAL_DIA_MM)
            except (TypeError, ValueError):
                return 400, {"error": "target must be a number (mm)"}
            if not 1.0 <= target <= 3.0:
                return 400, {"error": "target must be between 1.0 and 3.0 mm"}
            path += f"?target={target:.3f}"
        fetch = fetch or (lambda url: http_json(url, timeout=3, headers={"X-Indus3D-Action": "1"}))
        try:
            body = fetch(self.url.rstrip("/") + path)
        except Exception as e:  # noqa: BLE001
            return 502, {"error": f"daemon unreachable: {type(e).__name__}"}
        self._audit("sensor_action", f"filament sensor action: {action}"
                    + (f" (target {target:.3f} mm)" if action == "calibrate_span" else ""), "executed", now)
        return 200, body

    # -- view ------------------------------------------------------------------
    def summary(self):
        with self._lock:
            s = self.status or {}
            now = time.time()
            return {
                "enabled": bool(self.url), "url": self.url, "connected": self.connected,
                "fresh": self._fresh(now), "last_ok": self.last_ok, "last_error": self.last_error,
                "flow_owned_by_sensor": self.owns_flow_flag,
                "filament_present": s.get("filament_present"), "faults": s.get("faults"),
                "diameter_mm": s.get("diameter_mm"), "nozzle_diameter_mm": s.get("nozzle_diameter_mm"),
                "velocity_mm_s": s.get("velocity_mm_s"), "nozzle_flow_mm3_s": nozzle_flow_mm3_s(s) if s else None,
                "spool_used_g": s.get("spool_used_g"), "spool_remaining_g": s.get("spool_remaining_g"),
                "auto_flow_percent": s.get("auto_flow_percent"), "runout_countdown_mm": s.get("runout_countdown_mm"),
                "bowden_buffered_mm": s.get("bowden_buffered_mm"), "bed_jerk_mg": s.get("bed_jerk_mg"),
                "flow_input": self.flow_input_state,
                "spool_sync": {"enabled": self.spool.enabled, "recent": list(self.spool.results)},
                "events": list(self.events),
                "raw": s,
            }


def _notify(msg):
    from core.notifications import notify
    notify(msg)


def _make():
    from plugins.arbiter import arbiter
    return SensorBridge(notify=_notify, arbiter_external=arbiter.external)


bridge = _make()


def register_hooks(hooks) -> None:
    from plugins.run_recorder import recorder
    hooks.on("tick", bridge.tick, priority=45)
    hooks.on("controller.inputs", bridge.inputs, priority=40)
    recorder.on_finish(bridge.on_run_finish)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("plugin_filament_sensor", __name__, url_prefix="/api/v1/plugins/filament_sensor")

    @bp.route("", methods=["GET"])
    def sensor_status():
        return jsonify(bridge.summary())

    @bp.route("/action", methods=["POST"])
    def sensor_action():
        body = request.get_json(force=True, silent=True) or {}
        code, out = bridge.run_action(body.get("action"), body.get("target"), body.get("confirmed"))
        return jsonify(out), code

    app.register_blueprint(bp)
