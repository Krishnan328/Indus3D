#!/usr/bin/env python3
"""Host daemon for the ESP8266 bed sensor hub (ADXL345 on the bed + BME280 in the chamber).

The daemon is the ONLY process that talks to the hub's serial port (two processes cannot share
it). Everything else goes through its local HTTP API.

  * Keeps the serial link alive: finds the hub, reconnects with back-off, never resets it
    (DTR/RTS are kept low), re-applies the crash threshold after a reconnect or an ESP reset.
  * Parses the 1 Hz JSON telemetry and keeps the latest state with its age, so a silent link
    shows as disconnected instead of serving stale numbers as fresh.
  * On a bed crash (the ESP's immediate alert line, or the latched flag in telemetry) and ONLY
    while a print is running: POST /printer/print/pause to Moonraker first (no macro needed),
    then runs the BED_CRASH_HANDLER macro. A crash while idle or already paused is just logged:
    the handler moves the toolhead and must not run on an unhomed idle printer.
  * Captures high-speed shaper data on request (the hub switches to a faster baud for the
    session, since 1600 Hz needs ~240 kbit/s) and saves it as a Klipper-style CSV.
  * Logs telemetry to a size-rotated CSV (optional) for the Indus3D database ingest to use.

HTTP API, bound to 127.0.0.1 by default (POSTs need the header  X-Indus3D-Action: 1):
  GET  /telemetry  /status      latest hub state + connection info
  GET  /chamber                 chamber values only
  GET  /health                  {"ok", "connected", "age_s"}
  GET  /shaper/last             metadata of the last capture
  POST /reset_crash             clear the hub's crash latch
  POST /threshold               {"mg": 2500}   (500-8000)
  POST /shaper/capture          {"duration": 7, "rate": 1600, "baud": 921600?}
"""

import argparse
import csv
import glob
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_protocol as hp  # noqa: E402

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover - the daemon cannot run without it, tests inject a fake
    serial = None

log = logging.getLogger("bedhub")

UDEV_LINK = "/dev/esp8266_bed_hub"
ACTION_HEADER = "X-Indus3D-Action"
ALLOWED_RATES = (200, 400, 800, 1600, 3200)
ALLOWED_BAUDS = (115200, 230400, 460800, 921600)
THRESHOLD_RANGE = (500, 8000)
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "indus3d" / "bed_hub"


# ── serial helpers ───────────────────────────────────────────────────────────────────
def open_serial(port: str, baud: int):
    if serial is None:
        raise RuntimeError("pyserial is not installed")
    s = serial.Serial()
    s.port, s.baudrate, s.timeout, s.write_timeout = port, baud, 0.5, 1.0
    s.dtr = False          # an asserted DTR/RTS resets NodeMCU-style boards: that would clear the
    s.rts = False          # crash latch and the threshold every time the daemon (re)connects
    try:
        s.exclusive = True  # refuse to share the port with another process
    except AttributeError:
        pass
    s.open()
    return s


def candidate_ports() -> List[str]:
    """Serial devices that could be the hub, excluding Klipper MCUs (never touched)."""
    seen, out = set(), []
    for p in sorted(glob.glob("/dev/serial/by-id/*")) + sorted(glob.glob("/dev/serial/by-path/*")):
        real = os.path.realpath(p)
        if "Klipper" in p or real in seen:
            continue
        seen.add(real)
        out.append(p)
    return out


def bed_accel_line(line: str) -> bool:
    return line.startswith("{") and '"bed_accel"' in line


def probe_port(port: str, opener=open_serial, listen_s: float = 2.5, clock=time.time) -> bool:
    """Passive probe: the hub announces itself with a telemetry line every second. Nothing is
    ever written to an unknown device. A port held by another process (e.g. Klipper) just fails."""
    try:
        s = opener(port, 115200)
    except Exception:  # noqa: BLE001
        return False
    try:
        end = clock() + listen_s
        while clock() < end:
            if bed_accel_line(s.readline().decode("utf-8", errors="replace").strip()):
                return True
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass
    return False


def find_port(explicit: str, opener=open_serial, link: str = UDEV_LINK, exists=os.path.exists,
              candidates=candidate_ports, probe=probe_port) -> Optional[str]:
    if explicit and explicit.lower() != "auto":
        return explicit
    if exists(link):
        return link
    for p in candidates():
        if probe(p, opener):
            return p
    return None


# ── persistence / logging ────────────────────────────────────────────────────────────
class TelemetryCsv:
    HEADER = ["timestamp_iso", "uptime_sec", "accel_x_mg", "accel_y_mg", "accel_z_mg", "jerk_mg",
              "temp_c", "humidity_pct", "pressure_hpa", "crash_detected"]

    def __init__(self, path: Path, max_bytes: int = 5 * 1024 * 1024, keep: int = 3):
        self.path, self.max_bytes, self.keep = Path(path), max_bytes, keep
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _rotate(self):
        for i in range(self.keep - 1, 0, -1):
            src = Path(f"{self.path}.{i}")
            if src.exists():
                src.replace(Path(f"{self.path}.{i + 1}"))
        if self.path.exists():
            self.path.replace(Path(f"{self.path}.1"))
        old = Path(f"{self.path}.{self.keep + 1}")
        old.unlink(missing_ok=True)

    def write(self, data: Dict, when: float):
        if self.path.exists() and self.path.stat().st_size > self.max_bytes:
            self._rotate()
        new = not self.path.exists()
        bed, ch = data.get("bed_accel", {}), data.get("chamber", {})
        with open(self.path, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(self.HEADER)
            w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(when)) + "Z", data.get("uptime_sec", ""),
                        bed.get("x_mg", ""), bed.get("y_mg", ""), bed.get("z_mg", ""), bed.get("jerk_mg", ""),
                        "" if ch.get("temp_c") is None else ch.get("temp_c"),
                        "" if ch.get("humidity_pct") is None else ch.get("humidity_pct"),
                        "" if ch.get("pressure_hpa") is None else ch.get("pressure_hpa"),
                        bool(data.get("crash_detected"))])


def mqtt_payload(data: Dict, threshold_mg=None) -> Dict:
    """Flat, numeric-only JSON for Moonraker's [sensor] template (set_result needs numbers).
    Chamber fields are left out when the BME280 reports nothing, so a dead sensor shows as
    'no data' rather than as 0."""
    ch, bed = data.get("chamber") or {}, data.get("bed_accel") or {}
    out = {"crash_latched": 1 if data.get("crash_detected") else 0,
           "bed_jerk_mg": bed.get("jerk_mg", 0),
           "crash_threshold_mg": data.get("crash_threshold_mg", threshold_mg or 0)}
    for src, dst in (("temp_c", "chamber_temp_c"), ("humidity_pct", "chamber_humidity_pct"),
                     ("pressure_hpa", "chamber_pressure_hpa")):
        if isinstance(ch.get(src), (int, float)):
            out[dst] = ch[src]
    info = data.get("crash_info") or {}
    if data.get("crash_detected") and info.get("peak_jerk_mg") is not None:
        out["crash_peak_jerk_mg"] = info["peak_jerk_mg"]
    return out


class Job:
    def __init__(self, kind: str, **kw):
        self.kind, self.kw = kind, kw
        self.done = threading.Event()
        self.result: Optional[Dict] = None


# ── the daemon ────────────────────────────────────────────────────────────────────────
class HubDaemon:
    def __init__(self, port="auto", baud=115200, moonraker_url="http://127.0.0.1:7125", moonraker_key="",
                 act_on_crash=True, crash_cooldown_s=10.0, threshold_mg=None, data_dir=DEFAULT_DATA_DIR,
                 csv_log=True, stale_after_s=5.0, opener=open_serial, clock=time.time, sleep=time.sleep,
                 http=None, async_actions=True, finder=find_port, publisher=None):
        self.port_arg, self.baud = port, baud
        self.moonraker_url = (moonraker_url or "").rstrip("/")
        self.moonraker_key = moonraker_key
        self.act_on_crash, self.crash_cooldown_s = act_on_crash, crash_cooldown_s
        self.threshold_mg = threshold_mg
        self.data_dir = Path(data_dir)
        self.stale_after_s = stale_after_s
        self._opener, self._clock, self._sleep, self._finder = opener, clock, sleep, finder
        self._http = http or self._urllib_json
        self.async_actions = async_actions
        self.publisher = publisher                     # optional MqttPublisher (Moonraker [sensor] feed)

        self.ser = None
        self.port_in_use: Optional[str] = None
        self.running = True
        self.latest: Dict = {}
        self.last_update: Optional[float] = None
        self.last_error: Optional[str] = None
        self.reconnects = 0
        self.esp_resets = 0
        self._prev_uptime: Optional[int] = None
        self.responses: deque = deque(maxlen=50)
        self.jobs: "deque[Job]" = deque()
        self.jobs_lock = threading.Lock()
        self.last_crash: Optional[Dict] = None
        self._last_crash_handled = -1e18
        self._crash_latched_seen = False
        self._first_telemetry = True
        self.last_capture: Optional[Dict] = None
        self._csv = TelemetryCsv(self.data_dir / "telemetry.csv") if csv_log else None
        self._load_state()

    # -- state file ---------------------------------------------------------------------
    def _state_file(self) -> Path:
        return self.data_dir / "state.json"

    def _load_state(self):
        try:
            d = json.loads(self._state_file().read_text())
            if self.threshold_mg is None and isinstance(d.get("threshold_mg"), int):
                self.threshold_mg = d["threshold_mg"]
        except (OSError, ValueError):
            pass

    def _save_state(self):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._state_file().write_text(json.dumps({"threshold_mg": self.threshold_mg}))
        except OSError as e:
            log.warning("could not save state: %s", e)

    # -- HTTP to Moonraker ---------------------------------------------------------------
    def _urllib_json(self, method: str, url: str, body=None, timeout=2.0):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.moonraker_key:
            req.add_header("X-Api-Key", self.moonraker_key)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def print_state(self) -> Optional[str]:
        if not self.moonraker_url:
            return None
        try:
            r = self._http("GET", f"{self.moonraker_url}/printer/objects/query?print_stats")
            return r["result"]["status"]["print_stats"]["state"]
        except Exception as e:  # noqa: BLE001
            log.error("cannot read the print state from Moonraker: %s", e)
            return None

    # -- connection -----------------------------------------------------------------------
    def _connect(self) -> bool:
        port = self._finder(self.port_arg, self._opener)
        if not port:
            self.last_error = "hub not found (no serial device announced itself)"
            return False
        try:
            self.ser = self._opener(port, self.baud)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"cannot open {port}: {e}"
            return False
        self.port_in_use, self.last_error = port, None
        self.reconnects += 1
        self._prev_uptime = None
        self._first_telemetry = True      # a latch that was already set before we connected is not a new crash
        log.info("serial link up on %s @ %d baud", port, self.baud)
        self._apply_threshold()
        return True

    def _disconnect(self, why: str):
        log.warning("serial link down: %s", why)
        self.last_error = why
        try:
            if self.ser:
                self.ser.close()
        except Exception:  # noqa: BLE001
            pass
        self.ser = None

    def _apply_threshold(self):
        if self.threshold_mg:
            res = self._do_command(f"SET_CRASH_THRESHOLD {self.threshold_mg}", ("// CRASH_THRESHOLD_UPDATED",), 2.0)
            if not res["ok"]:
                log.warning("could not re-apply the crash threshold: %s", res.get("response"))

    # -- line handling ----------------------------------------------------------------------
    def handle_line(self, line: str):
        if not line:
            return
        if line.startswith("{") and line.endswith("}"):
            try:
                self.handle_telemetry(json.loads(line))
            except ValueError:
                log.debug("bad telemetry JSON: %r", line[:80])
            return
        if line.startswith("//") or line == "PONG":
            self.responses.append(line)
            crash = hp.parse_crash_line(line)
            if crash:
                self._on_crash(crash["jerk_mg"], crash["accel"], "alert")
            elif "ERROR" in line:
                log.warning("hub: %s", line)

    def handle_telemetry(self, data: Dict):
        now = self._clock()
        up = data.get("uptime_sec")
        if isinstance(up, int) and self._prev_uptime is not None and up + 2 < self._prev_uptime:
            self.esp_resets += 1
            log.warning("the hub restarted (uptime %s -> %s s): re-applying settings", self._prev_uptime, up)
            self._apply_threshold()
        if isinstance(up, int):
            self._prev_uptime = up
        self.latest, self.last_update = data, now
        latched = bool(data.get("crash_detected"))
        if self._first_telemetry:
            self._first_telemetry = False
            self._crash_latched_seen = latched
        elif latched and not self._crash_latched_seen:
            info = data.get("crash_info") or {}
            self._on_crash(int(info.get("peak_jerk_mg") or 0), info.get("accel_at_crash"), "telemetry")
        self._crash_latched_seen = latched
        self._publish(data)
        if self._csv:
            try:
                self._csv.write(data, now)
            except OSError as e:
                log.warning("csv log failed: %s", e)

    def _publish(self, data: Dict):
        if not self.publisher:
            return
        try:
            self.publisher.publish(json.dumps(mqtt_payload(data, self.threshold_mg)).encode())
        except Exception as e:                           # never let the feed disturb crash handling
            log.debug("mqtt publish failed: %s", e)

    # -- crash handling -----------------------------------------------------------------------
    def _on_crash(self, jerk_mg: int, accel, source: str):
        now = self._clock()
        self._crash_latched_seen = True
        event = {"ts": now, "jerk_mg": jerk_mg, "accel": accel, "source": source, "action": None}
        if now - self._last_crash_handled < self.crash_cooldown_s:
            event["action"] = {"result": "suppressed", "reason": "duplicate of the crash just handled"}
            return
        self._last_crash_handled = now
        self.last_crash = event
        log.error("BED CRASH detected via %s: jerk=%s mg accel=%s", source, jerk_mg, accel)
        if not self.act_on_crash:
            event["action"] = {"result": "disabled", "reason": "--no-act"}
            return
        if self.async_actions:
            threading.Thread(target=self._crash_action, args=(event,), daemon=True, name="crash-action").start()
        else:
            self._crash_action(event)

    def _crash_action(self, event: Dict):
        state = self.print_state()
        action = {"print_state": state}
        if state == "printing":
            action["pause"] = self._post_retry("/printer/print/pause")
            jerk = event["jerk_mg"] or 2000
            action["handler"] = self._post_retry("/printer/gcode/script", {"script": f"BED_CRASH_HANDLER JERK={jerk}"})
            action["result"] = "paused" if action["pause"] else "FAILED to pause"
        elif state == "paused":
            action["result"] = "ignored: print already paused"
        elif state is None:
            action["result"] = "FAILED: Moonraker unreachable, nothing was paused"
        else:
            action["result"] = f"ignored: no print running ({state})"
            # nothing was paused, so nobody will clear the latch: do it here, or the hub stays latched
            # and may not announce the next (real) crash. Only from the action thread: the serial
            # thread cannot wait on its own job queue.
            if self.async_actions:
                action["latch_cleared"] = bool(self.reset_crash().get("ok"))
        event["action"] = action
        (log.error if "FAILED" in action["result"] else log.warning)("crash response: %s", action["result"])

    def _post_retry(self, path: str, body=None, tries: int = 3) -> bool:
        for i in range(tries):
            try:
                self._http("POST", f"{self.moonraker_url}{path}", body if body is not None else {})
                return True
            except Exception as e:  # noqa: BLE001
                log.error("Moonraker POST %s failed (%d/%d): %s", path, i + 1, tries, e)
                self._sleep(0.3)
        return False

    # -- commands & captures (run on the I/O thread) ---------------------------------------------
    def _do_command(self, text: str, expect=(), timeout: float = 3.0) -> Dict:
        if not self.ser:
            return {"ok": False, "response": "not connected"}
        self.responses.clear()
        try:
            self.ser.write((text + "\n").encode())
            self.ser.flush()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "response": f"write failed: {e}"}
        end = self._clock() + timeout
        while self._clock() < end:
            for r in list(self.responses):
                if any(r.startswith(p) for p in expect):
                    return {"ok": True, "response": r}
                if r.startswith("// ERROR"):
                    return {"ok": False, "response": r}
            self.handle_line(self._read_line())
        return {"ok": False, "response": "no answer (old firmware, or the hub is busy)"}

    def _read_line(self) -> str:
        try:
            return self.ser.readline().decode("utf-8", errors="replace").strip()
        except Exception as e:  # noqa: BLE001
            self._disconnect(f"read error: {e}")
            return ""

    def _do_capture(self, duration: int, rate: int, baud: Optional[int]) -> Dict:
        if not self.ser:
            return {"ok": False, "error": "not connected"}
        need = rate * 15 / 0.85 * 10
        baud = baud or next((b for b in ALLOWED_BAUDS if b >= need), ALLOWED_BAUDS[-1])
        base = self.baud
        cmd = f"START_SHAPER {duration} {rate}" + (f" {baud}" if baud != base else "")
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\n").encode())
        self.ser.flush()

        # 1. the STARTED line arrives at the old baud and tells us the rate/baud actually used
        started, head, end = None, bytearray(), self._clock() + 3.0
        while self._clock() < end and started is None:
            head += self.ser.readline()
            s = hp.parse_session_started(bytes(head))
            if s:
                started = s
        if not started:
            return {"ok": False, "error": "the hub did not start a session (no STARTED line): "
                                          "old firmware, or the command was rejected"}
        link = started["baud"] or base
        if link != base:
            self.ser.baudrate = link
        buf = bytearray()
        # 2. binary stream until the ENDED marker (the hub restores its own baud after it)
        deadline = self._clock() + started["duration_s"] + 4.0
        seen_end = False
        while self._clock() < deadline:
            chunk = self.ser.read(getattr(self.ser, "in_waiting", 0) or 1)
            if chunk:
                buf += chunk
                if hp.ENDED_MARK in buf:
                    seen_end = True
                    break
        if not seen_end:
            try:
                self.ser.write(b"STOP_SHAPER\n")
                self.ser.flush()
                self._sleep(0.5)
                buf += self.ser.read(getattr(self.ser, "in_waiting", 0) or 0)
            except Exception:  # noqa: BLE001
                pass
        if link != base:
            self._sleep(0.05)
            self.ser.baudrate = base
        self._sleep(0.05)
        self.ser.reset_input_buffer()

        payload, _ = hp.split_capture(bytes(buf))
        samples, stats = hp.unpack_frames(payload)
        if len(samples) < 10:
            return {"ok": False, "error": f"only {len(samples)} valid samples received", "stats": stats}
        out_dir = self.data_dir / "captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / ("shaper-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime(self._clock())) + ".csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("time,accel_x,accel_y,accel_z\n")
            for t, x, y, z in samples:
                fh.write(f"{t:.6f},{x:.5f},{y:.5f},{z:.5f}\n")
        expected = started["duration_s"] * started["rate_hz"]
        loss = max(0.0, 1.0 - len(samples) / expected) * 100 if expected else 0.0
        meta = {"ok": True, "csv": str(path), "samples": len(samples), "requested_rate_hz": rate,
                "rate_hz": started["rate_hz"], "baud": link, "duration_s": started["duration_s"],
                "loss_pct": round(loss, 2), "stats": stats, "ended_marker": seen_end,
                "quality": "good" if loss < 2.0 and stats.get("bad_checksum", 0) == 0 else "poor"}
        self.last_capture = meta
        return meta

    def _process_jobs(self):
        with self.jobs_lock:
            job = self.jobs.popleft() if self.jobs else None
        if job is None:
            return
        try:
            if job.kind == "command":
                job.result = self._do_command(**job.kw)
            elif job.kind == "capture":
                job.result = self._do_capture(**job.kw)
            else:
                job.result = {"ok": False, "error": f"unknown job {job.kind}"}
        except Exception as e:  # noqa: BLE001
            log.exception("job failed")
            job.result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            job.done.set()

    def submit(self, kind: str, wait_s: float, **kw) -> Dict:
        job = Job(kind, **kw)
        with self.jobs_lock:
            self.jobs.append(job)
        if not job.done.wait(wait_s):
            return {"ok": False, "error": "timed out waiting for the serial link"}
        return job.result or {"ok": False, "error": "no result"}

    # -- public operations (called from the HTTP threads) ---------------------------------------
    def reset_crash(self) -> Dict:
        res = self.submit("command", 6.0, text="RESET_CRASH", expect=("// CRASH_RESET",), timeout=3.0)
        if res.get("ok"):
            self._crash_latched_seen = False
            self.latest = {**self.latest, "crash_detected": False}
            self.latest.pop("crash_info", None)
        return res

    def set_threshold(self, mg: int) -> Dict:
        lo, hi = THRESHOLD_RANGE
        if not isinstance(mg, int) or isinstance(mg, bool) or not lo <= mg <= hi:
            return {"ok": False, "error": f"threshold must be an integer {lo}-{hi} mg"}
        res = self.submit("command", 6.0, text=f"SET_CRASH_THRESHOLD {mg}",
                          expect=("// CRASH_THRESHOLD_UPDATED",), timeout=3.0)
        if res.get("ok"):
            self.threshold_mg = mg
            self._save_state()
        return res

    def capture_shaper(self, duration=7, rate=1600, baud=None) -> Dict:
        if not (isinstance(duration, int) and 1 <= duration <= 15):
            return {"ok": False, "error": "duration must be 1-15 s"}
        if rate not in ALLOWED_RATES:
            return {"ok": False, "error": f"rate must be one of {ALLOWED_RATES}"}
        if baud is not None and baud not in ALLOWED_BAUDS:
            return {"ok": False, "error": f"baud must be one of {ALLOWED_BAUDS}"}
        return self.submit("capture", duration + 25.0, duration=duration, rate=rate, baud=baud)

    # -- views ------------------------------------------------------------------------------------
    def snapshot(self) -> Dict:
        now = self._clock()
        age = None if self.last_update is None else round(now - self.last_update, 2)
        connected = bool(self.ser) and age is not None and age <= self.stale_after_s
        return {**self.latest, "connected": connected, "last_update": self.last_update, "age_s": age,
                "daemon": {"port": self.port_in_use, "baud": self.baud, "link_open": bool(self.ser),
                           "reconnects": self.reconnects, "esp_resets": self.esp_resets,
                           "last_error": self.last_error, "crash_threshold_mg": self.threshold_mg,
                           "act_on_crash": self.act_on_crash, "last_crash": self.last_crash,
                           "last_capture": self.last_capture}}

    # -- main loop ----------------------------------------------------------------------------------
    def run_forever(self):
        backoff = 1.0
        while self.running:
            if not self.ser:
                if self._connect():
                    backoff = 1.0
                else:
                    self._sleep(backoff)
                    backoff = min(10.0, backoff * 1.5)
                    self._fail_pending_jobs()
                    continue
            self._process_jobs()
            self.handle_line(self._read_line()) if self.ser else None

    def _fail_pending_jobs(self):
        with self.jobs_lock:
            jobs, self.jobs = list(self.jobs), deque()
        for j in jobs:
            j.result = {"ok": False, "error": "hub not connected"}
            j.done.set()

    def stop(self):
        self.running = False


# ── HTTP API ──────────────────────────────────────────────────────────────────────────────────
def make_handler(d: HubDaemon):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: Dict):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/telemetry", "/status", "/api/telemetry"):
                return self._send(200, d.snapshot())
            if path in ("/chamber", "/api/chamber"):
                return self._send(200, d.snapshot().get("chamber", {}))
            if path == "/health":
                s = d.snapshot()
                return self._send(200, {"ok": True, "connected": s["connected"], "age_s": s["age_s"]})
            if path == "/shaper/last":
                return self._send(200, d.last_capture or {})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?")[0]
            if self.headers.get(ACTION_HEADER) != "1":
                return self._send(403, {"error": f"{ACTION_HEADER}: 1 header required"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 2048)).decode() or "{}") if n else {}
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            if path in ("/reset_crash", "/api/reset_crash"):
                res = d.reset_crash()
            elif path == "/threshold":
                res = d.set_threshold(body.get("mg"))
            elif path == "/shaper/capture":
                res = d.capture_shaper(body.get("duration", 7), body.get("rate", 1600), body.get("baud"))
            else:
                return self._send(404, {"error": "not found"})
            self._send(200 if res.get("ok") else 502, res)

    return H


def serve(d: HubDaemon, host: str, port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), make_handler(d))
    threading.Thread(target=srv.serve_forever, daemon=True, name="hub-http").start()
    return srv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serial", default="auto", help="serial device, or 'auto' (udev link, then passive probe)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--host", default="127.0.0.1", help="API bind address (default: loopback only)")
    ap.add_argument("--port", type=int, default=7127, help="API port")
    ap.add_argument("--moonraker", default="http://127.0.0.1:7125")
    ap.add_argument("--moonraker-key", default=os.environ.get("MOONRAKER_API_KEY", ""))
    ap.add_argument("--no-act", action="store_true", help="log crashes but never pause the print")
    ap.add_argument("--crash-cooldown", type=float, default=10.0)
    ap.add_argument("--threshold", type=int, default=None, help="crash threshold in mg, re-applied after reconnects")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--no-csv", action="store_true")
    ap.add_argument("--mqtt", metavar="HOST[:PORT]", help="publish chamber/crash status to this MQTT broker "
                    "(feeds a Moonraker [sensor], see klipper/moonraker_bed_hub.conf)")
    ap.add_argument("--mqtt-topic", default="indus3d/bed_hub/state")
    ap.add_argument("--mqtt-user", default=os.environ.get("MQTT_USER", ""))
    ap.add_argument("--mqtt-password", default=os.environ.get("MQTT_PASSWORD", ""))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    publisher = None
    if args.mqtt:
        import mqtt_publish
        host, _, mport = args.mqtt.partition(":")
        publisher = mqtt_publish.MqttPublisher(host, int(mport or 1883), args.mqtt_topic, username=args.mqtt_user,
                                               password=args.mqtt_password).start()
    d = HubDaemon(port=args.serial, baud=args.baud, moonraker_url=args.moonraker, moonraker_key=args.moonraker_key,
                  act_on_crash=not args.no_act, crash_cooldown_s=args.crash_cooldown, threshold_mg=args.threshold,
                  data_dir=args.data_dir, csv_log=not args.no_csv, publisher=publisher)
    srv = serve(d, args.host, args.port)
    log.info("API on http://%s:%d/telemetry", args.host, args.port)
    signal.signal(signal.SIGTERM, lambda *_: d.stop())
    signal.signal(signal.SIGINT, lambda *_: d.stop())
    try:
        d.run_forever()
    finally:
        srv.shutdown()
        if d.ser:
            d.ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
