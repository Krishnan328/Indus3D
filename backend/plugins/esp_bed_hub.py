"""
plugins/esp_bed_hub.py  (C3)
------------------------------
Brings the ESP8266 bed hub (ADXL345 on the bed, BME280 in the chamber) into Indus3D through the
hub's host daemon (helpers/filament_sensor/esp8266_sensor_hub, REST on 127.0.0.1:7127). A background
thread polls its /telemetry once a second (never the control loop's thread).

* Visibility   bed acceleration / jerk, chamber climate, the crash latch, and how fresh the data is.
               A daemon that is up while the hub is unplugged is reported as disconnected, never as
               stale numbers. The chamber values feed /api/v1/environment and chamber_environment.
* Storage      every new 1 Hz sample goes into the SQLite table telemetry_samples
               (timestamp_utc ISO-8601, chamber_temp_c, chamber_humidity_pct, chamber_pressure_hpa,
               bed_accel_x_mg/_y_mg/_z_mg, bed_jerk_mg, crash_detected). Rows are batched (SD-card
               friendly) and pruned after INDUS3D_BED_TELEMETRY_DAYS (default 7).
* Crash        a crash (the hub's latch, or a new crash recorded by the daemon) raises a notification
               and an action_log row that say what the daemon did about it (paused / failed to pause).
               The daemon pauses the print itself through Moonraker; this plugin never pauses.
               While the crash is latched, every corrective command is HELD (vetoed): the handler has
               cooled the hotend on purpose and a queued M104/M221 must not undo that or act on a
               paused print. INDUS3D_BED_CRASH_HOLD=0 turns the hold off.
* Exclude      opt-in, INDUS3D_BED_CRASH_EXCLUDE_OBJECT=1: after a crash, while the print is paused,
               EXCLUDE_OBJECT the object being printed so the resume skips it. Off by default: an
               acceleration spike says the bed was hit, not WHICH object caused it.
* Actions      reset the hub's latch / set its threshold, proxied through Indus3D's authenticated API.

INDUS3D_BED_HUB_URL   default http://127.0.0.1:7127 ; set empty to disable. (INDUS3D_ESP_HUB_URL is
                      still honoured as an alias.)

GET  /api/v1/plugins/esp_bed_hub
GET  /api/v1/plugins/esp_bed_hub/samples?minutes=60&limit=600
POST /api/v1/plugins/esp_bed_hub/action   {"action": "reset_crash|set_threshold", "value": 2500, "confirmed": true}
"""

import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone

from core.plugin_hooks import ctx_veto
from plugins._common import Poller, http_json, notify_critical_safe

PLUGIN_INFO = {
    "title": "ESP8266 bed hub",
    "description": "Bed acceleration, chamber climate and crash latch from the ESP8266 hub; stores telemetry and holds corrections after a crash.",
}

DEFAULT_URL = "http://127.0.0.1:7127"
POLL_S = 1.0
FLUSH_EVERY_N, FLUSH_EVERY_S = 30, 30.0
PRUNE_EVERY_S = 3600.0
COLUMNS = ("timestamp_utc", "chamber_temp_c", "chamber_humidity_pct", "chamber_pressure_hpa",
           "bed_accel_x_mg", "bed_accel_y_mg", "bed_accel_z_mg", "bed_jerk_mg", "crash_detected")
THRESHOLD_RANGE = (500, 8000)
OBJECT_NAME = re.compile(r"^[\w.\-]{1,100}$")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _env_url() -> str:
    e = os.environ
    for key in ("INDUS3D_BED_HUB_URL", "INDUS3D_ESP_HUB_URL"):
        if key in e:
            return e[key].strip()
    return DEFAULT_URL


# ── SQLite storage ────────────────────────────────────────────────────────────
class TelemetryStore:
    """telemetry_samples with batched writes and retention. The plugin owns the table (CREATE TABLE
    IF NOT EXISTS), so it needs no migration."""

    def __init__(self, connect=None, retention_days=None, enabled=None):
        self._connect = connect
        self.retention_days = float(os.environ.get("INDUS3D_BED_TELEMETRY_DAYS", 7)) if retention_days is None else retention_days
        self.enabled = os.environ.get("INDUS3D_BED_TELEMETRY_DB", "1") != "0" if enabled is None else enabled
        self.buffer = deque(maxlen=5000)               # bounded: a broken database must not grow memory
        self.last_flush = time.time()
        self.last_prune = 0.0
        self.last_error = None
        self.rows_written = 0
        self._ready = False
        self._lock = threading.Lock()

    def _conn(self):
        if self._connect:
            return self._connect()
        from db.models import get_connection
        return get_connection()

    def _ensure(self, conn):
        if self._ready:
            return
        conn.execute("""CREATE TABLE IF NOT EXISTS telemetry_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            chamber_temp_c REAL, chamber_humidity_pct REAL, chamber_pressure_hpa REAL,
            bed_accel_x_mg REAL, bed_accel_y_mg REAL, bed_accel_z_mg REAL, bed_jerk_mg REAL,
            crash_detected INTEGER DEFAULT 0)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_samples_ts ON telemetry_samples(timestamp_utc)")
        self._ready = True

    def add(self, now: float, d: dict, force_flush=False):
        if not self.enabled:
            return
        bed, ch = d.get("bed_accel") or {}, d.get("chamber") or {}
        row = (_iso(now), ch.get("temp_c"), ch.get("humidity_pct"), ch.get("pressure_hpa"),
               bed.get("x_mg"), bed.get("y_mg"), bed.get("z_mg"), bed.get("jerk_mg"), 1 if d.get("crash_detected") else 0)
        with self._lock:
            self.buffer.append(row)
            due = len(self.buffer) >= FLUSH_EVERY_N or now - self.last_flush >= FLUSH_EVERY_S
        if due or force_flush:
            self.flush(now)

    def flush(self, now: float = None):
        now = now or time.time()
        with self._lock:
            rows, self.buffer = list(self.buffer), deque(maxlen=self.buffer.maxlen)
        self.last_flush = now
        if not rows:
            return
        try:
            conn = self._conn()
            try:
                self._ensure(conn)
                conn.executemany(f"INSERT INTO telemetry_samples ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})", rows)
                if self.retention_days > 0 and now - self.last_prune >= PRUNE_EVERY_S:
                    conn.execute("DELETE FROM telemetry_samples WHERE timestamp_utc < ?",
                                 (_iso(now - self.retention_days * 86400),))
                    self.last_prune = now
                conn.commit()
            finally:
                conn.close()
            self.rows_written += len(rows)
            self.last_error = None
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            with self._lock:                            # keep them for the next attempt
                self.buffer.extendleft(reversed(rows))
            logging.info(f"⚠️  esp_bed_hub: could not store telemetry: {e}")

    def recent(self, minutes: float = 60, limit: int = 600) -> list:
        """Rows of the last `minutes`, thinned to at most `limit` (every n-th row)."""
        self.flush()
        conn = self._conn()
        try:
            self._ensure(conn)
            cutoff = _iso(time.time() - minutes * 60)
            n = conn.execute("SELECT COUNT(*) FROM telemetry_samples WHERE timestamp_utc >= ?", (cutoff,)).fetchone()[0]
            step = max(1, -(-n // max(1, limit)))
            cur = conn.execute(f"SELECT {','.join(COLUMNS)} FROM telemetry_samples WHERE timestamp_utc >= ? "
                               "AND (id % ?) = 0 ORDER BY id", (cutoff, step))
            return [dict(zip(COLUMNS, r)) for r in cur.fetchall()]
        finally:
            conn.close()


# ── the plugin ────────────────────────────────────────────────────────────────
class EspHub:
    def __init__(self, url=None, fetch=None, notify=None, store=None, post=None, moonraker=None,
                 hold=None, exclude_object=None, audit=None):
        self.url = _env_url() if url is None else url
        self._fetch = fetch or (lambda u: http_json(u.rstrip("/") + "/telemetry", timeout=1.5))
        self._post = post or (lambda path, body: http_json(self.url.rstrip("/") + path, timeout=8, method="POST", body=body,
                                                           headers={"X-Indus3D-Action": "1"}))
        self._moonraker = moonraker or self._moonraker_default
        self.notify = notify or (lambda message: notify_critical_safe("bed_crash", message))
        self._audit = audit or self._log_action
        self.store = store if store is not None else TelemetryStore()
        self.hold = os.environ.get("INDUS3D_BED_CRASH_HOLD", "1") != "0" if hold is None else hold
        self.exclude_object = os.environ.get("INDUS3D_BED_CRASH_EXCLUDE_OBJECT", "0") == "1" if exclude_object is None else exclude_object
        self.data = None
        self.connected = False                          # the daemon answers
        self.hub_ok = False                             # ... and the hub behind it is delivering data
        self.last_ok = None
        self.last_error = None
        self.crash_latched = False
        self._last_sample_key = None
        self._seen_crash_ts = None
        self.events = deque(maxlen=50)
        self._poller = Poller(self.poll_once, POLL_S, "esp-bed-hub")

    @property
    def enabled(self):
        return bool(self.url)

    # -- polling ------------------------------------------------------------------------
    def poll_once(self, now=None):
        now = now or time.time()
        try:
            d = self._fetch(self.url)
        except Exception as e:  # noqa: BLE001
            if self.connected:
                logging.info(f"ESP bed hub unreachable: {e}")
            self.connected = self.hub_ok = False
            self.last_error = f"{type(e).__name__}: {e}"
            return None
        self.data, self.connected, self.last_ok, self.last_error = d, True, now, None
        self.hub_ok = bool(d.get("connected", True))
        if not self.hub_ok:
            self.last_error = (d.get("daemon") or {}).get("last_error") or "hub not delivering data"
            return d
        latched = bool(d.get("crash_detected"))
        last = (d.get("daemon") or {}).get("last_crash") or {}
        new_daemon_crash = last.get("ts") is not None and last.get("ts") != self._seen_crash_ts
        if (latched and not self.crash_latched) or new_daemon_crash:
            self._seen_crash_ts = last.get("ts", self._seen_crash_ts)
            self._on_crash(now, d, last)
        self.crash_latched = latched
        key = d.get("last_update")
        if key is None or key != self._last_sample_key:
            self._last_sample_key = key
            self.store.add(now, d)
        return d

    def _on_crash(self, now, d, last):
        info = d.get("crash_info") or {}
        jerk = last.get("jerk_mg") or info.get("peak_jerk_mg")
        action = (last.get("action") or {})
        result = action.get("result", "reported by the hub")
        ev = {"ts": now, "kind": "crash", "peak_jerk_mg": jerk, "action": result, "print_state": action.get("print_state")}
        self.events.appendleft(ev)
        failed = "FAILED" in str(result)
        self.notify(f"💥 Indus3D bed hub: crash detected (jerk {jerk if jerk is not None else '?'} mg) — "
                    + (f"⚠️ {result}. PAUSE THE PRINT YOURSELF." if failed else f"{result}."))
        self._audit(now, jerk, result)
        self.store.add(now, d, force_flush=True)
        if self.exclude_object:
            ev["excluded_object"] = self._exclude_current_object()

    @staticmethod
    def _log_action(now, jerk, result):
        try:
            from db.models import get_connection
            conn = get_connection()
            try:
                conn.execute("INSERT INTO action_log (timestamp, alert_id, gcode, description, status) VALUES (?, ?, ?, ?, ?)",
                             (now, "esp_bed_hub:crash", "", f"Bed crash, jerk {jerk} mg: {result}", "detected"))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            logging.info(f"⚠️  esp_bed_hub: could not write action_log: {e}")

    # -- opt-in EXCLUDE_OBJECT ---------------------------------------------------------------
    @staticmethod
    def _moonraker_default(method, path, body=None):
        from config.settings import settings
        return http_json(settings.moonraker_url.rstrip("/") + path, timeout=3, method=method, body=body)

    def _exclude_current_object(self):
        """Name of the object excluded, or a short reason why nothing was."""
        try:
            st = self._moonraker("GET", "/printer/objects/query?exclude_object&print_stats")["result"]["status"]
            if (st.get("print_stats") or {}).get("state") != "paused":
                return "skipped: print not paused"
            name = (st.get("exclude_object") or {}).get("current_object")
            if not name or not OBJECT_NAME.match(str(name)):
                return "skipped: no usable current object"
            self._moonraker("POST", "/printer/gcode/script", {"script": f"EXCLUDE_OBJECT NAME={name}"})
            return name
        except Exception as e:  # noqa: BLE001
            return f"failed: {type(e).__name__}"

    # -- hooks -------------------------------------------------------------------------------
    def hold_active(self) -> bool:
        return bool(self.hold and self.enabled and self.hub_ok and self.crash_latched)

    def filter_commands(self, commands, ctx):
        if not commands or not self.hold_active():
            return commands
        for c in commands:
            ctx_veto(ctx, c, "esp_bed_hub", "bed crash latched: corrections are held until the crash is cleared")
        return []

    def chamber(self, max_age_s=10.0, now=None):
        """{"temp_c","humidity_pct","pressure_hpa"} when fresh and valid, else None."""
        now = now or time.time()
        if not (self.connected and self.hub_ok and self.last_ok and now - self.last_ok <= max_age_s and self.data):
            return None
        c = self.data.get("chamber") or {}
        return c if c.get("temp_c") is not None else None

    def tick(self, snap, ctx):
        if self.enabled:
            self._poller.start()

    # -- actions -----------------------------------------------------------------------------
    def run_action(self, action, value=None, confirmed=False):
        """(http_status, body). Reset and threshold changes need confirmed=true."""
        if not self.enabled:
            return 503, {"error": "ESP bed hub integration is disabled"}
        if confirmed is not True:
            return 400, {"error": "confirmation required"}
        try:
            if action == "reset_crash":
                res = self._post("/reset_crash", {})
            elif action == "set_threshold":
                if isinstance(value, bool) or not isinstance(value, int) or not THRESHOLD_RANGE[0] <= value <= THRESHOLD_RANGE[1]:
                    return 400, {"error": f"value must be an integer between {THRESHOLD_RANGE[0]} and {THRESHOLD_RANGE[1]} mg"}
                res = self._post("/threshold", {"mg": value})
            else:
                return 400, {"error": "unknown action"}
        except Exception as e:  # noqa: BLE001
            return 502, {"error": f"hub daemon unreachable: {e}"}
        if not res.get("ok"):
            return 502, {"error": res.get("error") or res.get("response") or "the hub refused"}
        return 200, {"ok": True, "message": "crash latch cleared" if action == "reset_crash" else f"threshold set to {value} mg"}

    # -- views -------------------------------------------------------------------------------
    def status(self):
        d = self.data or {}
        daemon = d.get("daemon") or {}
        return {"enabled": self.enabled, "url": self.url or None, "connected": self.connected, "hub_connected": self.hub_ok,
                "age_s": d.get("age_s"), "last_ok": self.last_ok, "last_error": self.last_error,
                "crash_latched": self.crash_latched, "hold_active": self.hold_active(),
                "crash_threshold_mg": d.get("crash_threshold_mg", daemon.get("crash_threshold_mg")),
                "bed_accel": d.get("bed_accel") if self.hub_ok else None, "chamber": self.chamber(),
                "crash_info": d.get("crash_info"), "last_crash": daemon.get("last_crash"),
                "events": list(self.events),
                "storage": {"enabled": self.store.enabled, "rows_written": self.store.rows_written,
                            "buffered": len(self.store.buffer), "retention_days": self.store.retention_days,
                            "last_error": self.store.last_error}}


hub = EspHub()


def register_hooks(hooks) -> None:
    hooks.on("tick", hub.tick, priority=46)
    hooks.on("commands.filter", hub.filter_commands, priority=5)       # before anything else may re-heat


def register_routes(app) -> None:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("plugin_esp_bed_hub", __name__, url_prefix="/api/v1/plugins/esp_bed_hub")

    @bp.route("", methods=["GET"])
    def hub_status():
        return jsonify(hub.status())

    @bp.route("/samples", methods=["GET"])
    def hub_samples():
        try:
            minutes = min(max(float(request.args.get("minutes", 60)), 1), 7 * 24 * 60)
            limit = min(max(int(request.args.get("limit", 600)), 10), 5000)
        except ValueError:
            return jsonify({"error": "minutes and limit must be numbers"}), 400
        try:
            return jsonify({"samples": hub.store.recent(minutes, limit)})
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": f"storage unavailable: {type(e).__name__}"}), 503

    @bp.route("/action", methods=["POST"])
    def hub_action():
        body = request.get_json(force=True, silent=True) or {}
        code, out = hub.run_action(body.get("action"), body.get("value"), body.get("confirmed"))
        return jsonify(out), code

    app.register_blueprint(bp)
