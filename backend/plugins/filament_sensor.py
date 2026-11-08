"""
plugins/filament_sensor.py  (C1)
---------------------------------
Bridge to the smart filament sensor host daemon (helpers/filament_sensor,
REST on :7126). Polls its /status in a background thread (never on the
telemetry thread) and:

* exposes the latest reading and a derived summary,
* notifies once when the sensor reports a fault or the filament leaves the
  sensor mid-print,
* tells the arbiter when the daemon is writing M221 (auto-flow), so Indus3D's
  flow loop yields instead of fighting it. Detected from the daemon's reported
  ``auto_flow_percent`` leaving 100 %, or declared via INDUS3D_SENSOR_INI
  (enable_auto_flow = true).

INDUS3D_SENSOR_URL   default http://127.0.0.1:7126 ; set empty to disable
INDUS3D_SENSOR_INI   optional path to indus3d_sensor.ini

GET /api/v1/plugins/filament_sensor
"""

import configparser
import json
import logging
import os
import threading
import time
import urllib.request

PLUGIN_INFO = {
    "title": "Filament sensor bridge",
    "description": "Reads the smart filament sensor daemon, raises fault/runout alerts, and keeps the flow loop from fighting its auto-flow.",
}

POLL_S = 2.0
AUTO_FLOW_HOLD_S = 120.0   # keep treating flow as externally owned this long after the last deviation
FLOW_EPS = 0.5


def fetch_status(url: str, timeout: float = 1.0) -> dict:
    with urllib.request.urlopen(url.rstrip("/") + "/status", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ini_auto_flow(path):
    if not path or not os.path.isfile(path):
        return None
    cp = configparser.ConfigParser()
    cp.read(path)
    return cp.getboolean("features", "enable_auto_flow", fallback=False)


class SensorBridge:
    def __init__(self, url=None, ini_path=None, notify=None, arbiter_external=None):
        self.url = os.environ.get("INDUS3D_SENSOR_URL", "http://127.0.0.1:7126") if url is None else url
        self.ini_path = os.environ.get("INDUS3D_SENSOR_INI", "") if ini_path is None else ini_path
        self.notify = notify
        self.external = arbiter_external if arbiter_external is not None else set()  # arbiter's set
        self.status = None
        self.connected = False
        self.last_ok = None
        self.last_error = None
        self.auto_flow_seen_at = None
        self.owns_flow_flag = False
        self.alerted = set()
        self.print_state = None
        self._started = False
        self._lock = threading.Lock()

    # polling ---------------------------------------------------------------
    def poll_once(self, fetch=fetch_status, now=None):
        now = now if now is not None else time.time()
        try:
            data = fetch(self.url)
        except Exception as e:  # noqa: BLE001 — an absent sensor is normal
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
            self.auto_flow_seen_at = now
        self._update_arbiter(now)
        self._alerts(data)
        return data

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

    def _alerts(self, data):
        faults = data.get("faults", "NORMAL")
        runout = self.print_state == "printing" and data.get("filament_present") is False
        for key, cond, msg in (
            ("fault", faults not in ("NORMAL", None, ""), f"filament sensor fault: {faults}"),
            ("runout", runout, "filament left the sensor during a print"),
        ):
            if cond and key not in self.alerted:
                self.alerted.add(key)
                if self.notify:
                    try:
                        self.notify(f"🧵 Indus3D: {msg}")
                    except Exception:  # noqa: BLE001
                        pass
            elif not cond:
                self.alerted.discard(key)

    def _loop(self):
        while True:
            self.poll_once()
            time.sleep(POLL_S)

    def tick(self, snap, ctx):
        self.print_state = snap.get("print_state")
        if not self._started and self.url:
            self._started = True
            threading.Thread(target=self._loop, daemon=True, name="filament-sensor-poll").start()

    def summary(self):
        with self._lock:
            s = self.status or {}
            return {
                "enabled": bool(self.url), "url": self.url, "connected": self.connected,
                "last_ok": self.last_ok, "last_error": self.last_error,
                "flow_owned_by_sensor": self.owns_flow_flag,
                "filament_present": s.get("filament_present"), "faults": s.get("faults"),
                "diameter_mm": s.get("diameter_mm"), "spool_remaining_g": s.get("spool_remaining_g"),
                "auto_flow_percent": s.get("auto_flow_percent"),
                "runout_countdown_mm": s.get("runout_countdown_mm"),
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
    hooks.on("tick", bridge.tick, priority=45)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_filament_sensor", __name__, url_prefix="/api/v1/plugins/filament_sensor")

    @bp.route("", methods=["GET"])
    def sensor_status():
        return jsonify(bridge.summary())

    app.register_blueprint(bp)
