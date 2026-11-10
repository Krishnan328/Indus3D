"""
plugins/usb_link_health.py
----------------------------
Watches the USB links between the host and the printer's MCUs (mainboard,
toolhead board, probe, sensors) and tells you *which hub, port or cable* is
failing, before Klipper reports "Lost communication with MCU".

Why: Klipper/Moonraker disconnects are usually a symptom. When every MCU is on
USB, one flaky hub or cable drops all of them at once, and Klipper only sees
the result. This plugin looks at the cause.

Two sources, no root needed:
  * sysfs  (/sys/bus/usb/devices) every second: which devices are present,
    their hub chain, and when one disappears or re-enumerates (device number
    changes). Always available.
  * kernel log via `journalctl -k` every 5 s, when the service user may read
    it: protocol errors (`clear tt … error -71`), "Cannot enable. Maybe the USB
    cable is bad?", enumeration failures, over-current. Without it the plugin
    still works from sysfs and says so; to enable it, add the service user to
    the `systemd-journal` group.

What it reports
  * events: device_lost, hub_drop (≥3 devices under one top hub within 3 s),
    flap (lost, then back within 30 s = unstable link), offline (lost and not
    back: normally just the printer being switched off), error_burst (many
    protocol errors in a minute = link degrading),
  * suspects: ports/hubs ranked by drops and errors, with the hub chain depth
    and what hangs below them,
  * a notification (rate-limited) when a device vanishes during a print, on a
    flap, a hub drop or an error burst.

Warn-only: it never touches the printer. Counters persist in the plugin data
dir. INDUS3D_USB_MONITOR=0 disables it. INDUS3D_USB_BURST_ERRORS (default 20)
sets the error-burst threshold.

GET /api/v1/plugins/usb_link_health
"""

import logging
import os
import re
import shutil
import subprocess
import time
from collections import Counter, deque
from pathlib import Path

from plugins._common import Poller, data_dir, notify_safe, read_json, write_json

PLUGIN_INFO = {
    "title": "USB link health",
    "description": "Finds the hub, port or cable behind MCU disconnects, from sysfs and the kernel log. Warn-only.",
}

SYSFS = "/sys/bus/usb/devices"
POLL_S = 1.0
KLOG_EVERY_S = 5.0
HUB_DROP_MIN = 3
HUB_DROP_WINDOW_S = 3.0
FLAP_S = 30.0
BURST_WINDOW_S = 60.0
BURST_REARM_S = 120.0
NOTIFY_GAP_S = 600.0
SAVE_EVERY_S = 60.0

_PATH = r"(\d+-\d+(?:\.\d+)*)"
RE_DISCONNECT = re.compile(rf"usb {_PATH}: USB disconnect")
RE_TT = re.compile(rf"usb {_PATH}: clear tt \d+ .*error -\d+")
RE_CABLE = re.compile(rf"usb {_PATH}-port(\d+): Cannot enable")
RE_ENUM = re.compile(rf"usb {_PATH}: (?:device not accepting address|unable to enumerate|device descriptor read)")
RE_OVERCURRENT = re.compile(rf"usb {_PATH}.*over-current", re.I)
RE_UNIX_TS = re.compile(r"^(\d+\.\d+)\s")

HINTS = {
    "cable": "the cable/connector on this port is marginal (kernel: 'Cannot enable. Maybe the USB cable is bad?')",
    "tt": "protocol errors on this hub: unstable hub, its power supply, or a bad cable upstream of it",
    "enum": "devices fail to enumerate on this hub/port: power or cable",
    "overcurrent": "over-current on this port: a short or an overloaded supply",
}


def parent_of(path: str):
    """'3-2.3.1' -> '3-2.3'; '3-2' -> None (top-level hub on the root port)."""
    bus, _, rest = path.partition("-")
    parts = rest.split(".")
    return None if len(parts) == 1 else f"{bus}-{'.'.join(parts[:-1])}"


def top_of(path: str) -> str:
    bus, _, rest = path.partition("-")
    return f"{bus}-{rest.split('.')[0]}"


def depth_of(path: str) -> int:
    """Hub tiers between the host and the device (a device on root port 3-2 is 0)."""
    return path.partition("-")[2].count(".")


def parse_klog_line(line: str):
    """-> (timestamp|None, kind, path) or None. kinds: disconnect, tt, cable, enum, overcurrent."""
    m = RE_UNIX_TS.match(line)
    ts = float(m.group(1)) if m else None
    for kind, rx in (("disconnect", RE_DISCONNECT), ("tt", RE_TT), ("cable", RE_CABLE),
                     ("enum", RE_ENUM), ("overcurrent", RE_OVERCURRENT)):
        mm = rx.search(line)
        if mm:
            return ts, kind, mm.group(1)
    return None


def _read(p: Path, default=""):
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def scan_sysfs(root=SYSFS) -> dict:
    """{path: info} for every USB device (interfaces and root hubs skipped)."""
    out = {}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        if ":" in name or name.startswith("usb"):
            continue
        d = Path(root) / name
        out[name] = {
            "path": name, "devnum": _read(d / "devnum"), "vid": _read(d / "idVendor"), "pid": _read(d / "idProduct"),
            "product": _read(d / "product"), "manufacturer": _read(d / "manufacturer"),
            "serial": _read(d / "serial"), "speed": _read(d / "speed"),
            "is_hub": _read(d / "bDeviceClass") == "09",
        }
    return out


def label(info: dict) -> str:
    if not info:
        return "unknown device"
    bits = [info.get("manufacturer"), info.get("product")]
    name = " ".join(b for b in bits if b) or f"{info.get('vid')}:{info.get('pid')}"
    return f"{name} [{info['path']}]"


def is_klipper_mcu(info: dict) -> bool:
    return (info or {}).get("manufacturer", "").lower() == "klipper"


def journal_reader(since_ts: float):
    """Kernel log lines since ``since_ts`` via journalctl, or None if unreadable."""
    if shutil.which("journalctl") is None:
        return None
    try:
        r = subprocess.run(["journalctl", "-k", "-o", "short-unix", "--no-pager", "-q",
                            "--since", f"@{int(since_ts)}"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.splitlines()


class UsbLinkHealth:
    def __init__(self, sysfs=SYSFS, read_klog=journal_reader, notify=notify_safe, state_path=None, burst=None):
        self.sysfs = sysfs
        self._read_klog = read_klog
        self.notify = notify
        self._state_path = state_path
        self.burst_n = int(os.environ.get("INDUS3D_USB_BURST_ERRORS", 20)) if burst is None else burst
        self.known = {}                 # path -> info (current)
        self.names = {}                 # path -> last known info (survives disconnects)
        self.pending = {}               # path -> {"t", "info"}: lost, waiting to see if it comes back
        self.recent_lost = deque()      # (t, path)
        self.events = deque(maxlen=100)
        self.counters = {"sysfs_disconnects": Counter(), "kernel_disconnects": Counter(), "tt": Counter(),
                         "cable": Counter(), "enum": Counter(), "overcurrent": Counter()}
        self.err_times = deque()
        self.burst_raised_at = None
        self.print_state = None
        self.klog_available = None      # None = untried
        self._klog_cursor = None
        self._last_klog = 0.0
        self._last_save = 0.0
        self._last_notified = {}
        self._first = True
        self._loaded = False

    # -- persistence -----------------------------------------------------------
    def _file(self):
        return self._state_path or (data_dir() / "usb_link_health.json")

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        d = read_json(self._file(), {})
        for k, c in d.get("counters", {}).items():
            if k in self.counters:
                self.counters[k] = Counter(c)
        for e in d.get("events", []):
            self.events.append(e)

    def save(self, now=None):
        try:
            write_json(self._file(), {"counters": {k: dict(v) for k, v in self.counters.items()},
                                      "events": list(self.events)})
        except OSError as e:
            logging.info(f"usb_link_health: could not save state: {e}")
        self._last_save = now or time.time()

    # -- events ----------------------------------------------------------------
    def _event(self, kind, now, detail, paths=(), notify_msg=None, severity="info"):
        ev = {"ts": now, "kind": kind, "severity": severity, "detail": detail, "paths": list(paths),
              "print_state": self.print_state}
        self.events.appendleft(ev)
        if severity != "info":
            logging.warning(f"🔌 usb_link_health [{kind}] {detail}")
        if notify_msg and now - self._last_notified.get(kind, -1e18) >= NOTIFY_GAP_S:
            self._last_notified[kind] = now
            self.notify(f"🔌 Indus3D USB: {notify_msg}")

    # -- sysfs -----------------------------------------------------------------
    def poll_sysfs(self, now=None):
        now = now or time.time()
        self._load()
        cur = scan_sysfs(self.sysfs)
        for p, info in cur.items():
            self.names[p] = info
        if self._first:
            self.known, self._first = cur, False
            return
        prev = self.known
        lost = [p for p in prev if p not in cur]
        renum = [p for p in prev if p in cur and prev[p]["devnum"] != cur[p]["devnum"]]
        for p in lost + renum:
            self.counters["sysfs_disconnects"][p] += 1
            self.recent_lost.append((now, p))
            self.pending[p] = {"t": now, "info": prev[p]}
        # recovered?
        for p in list(self.pending):
            if p in cur and (p not in lost):
                gone = self.pending.pop(p)
                dt = now - gone["t"]
                if dt <= FLAP_S:
                    self._event("flap", now, f"{label(cur[p])} dropped and came back after {dt:.1f}s — unstable link",
                                [p], f"{label(cur[p])} dropped and re-appeared after {dt:.0f}s (unstable link; "
                                     f"{depth_of(p)} hub tier(s) deep)", "warn")
        # devices gone for good
        for p, g in list(self.pending.items()):
            if p not in cur and now - g["t"] > FLAP_S:
                self.pending.pop(p)
                self._event("offline", now, f"{label(g['info'])} did not come back (printer switched off or unplugged)", [p])
        self.known = cur

        while self.recent_lost and now - self.recent_lost[0][0] > HUB_DROP_WINDOW_S:
            self.recent_lost.popleft()
        if lost or renum:
            self._classify_drop(now, lost + renum, prev)

    def _classify_drop(self, now, paths, prev):
        by_top = {}
        for _, p in self.recent_lost:
            by_top.setdefault(top_of(p), set()).add(p)
        for top, ps in by_top.items():
            if len(ps) >= HUB_DROP_MIN and not any(e["kind"] == "hub_drop" and e["paths"][:1] == [top]
                                                   and now - e["ts"] < HUB_DROP_WINDOW_S for e in self.events):
                names = ", ".join(label(self.names.get(p)) for p in sorted(ps))
                printing = self.print_state in ("printing", "paused")
                # Switching the printer off also drops everything at once, so only alert
                # immediately during a print; otherwise a 'flap' alert fires if they return.
                self._event("hub_drop", now, f"{len(ps)} devices under {top} vanished within {HUB_DROP_WINDOW_S:.0f}s: {names}",
                            [top] + sorted(ps),
                            (f"{len(ps)} devices behind hub {top} dropped at once ({names}) — the hub, its power or "
                             "its cable to the host") if printing else None,
                            "critical" if printing else "warn")
                return
        for p in paths:
            info = prev.get(p) or self.names.get(p)
            sev = "critical" if (self.print_state in ("printing", "paused") and is_klipper_mcu(info)) else "info"
            msg = None
            if sev == "critical":
                msg = f"{label(info)} vanished during a print ({depth_of(p)} hub tier(s) deep)"
            self._event("device_lost", now, f"{label(info)} disappeared", [p], msg, sev)

    # -- kernel log ------------------------------------------------------------
    def poll_klog(self, now=None):
        now = now or time.time()
        if self.klog_available is False:
            return
        since = self._klog_cursor or (now - KLOG_EVERY_S)
        lines = self._read_klog(since)
        if lines is None:
            if self.klog_available is None:
                logging.info("usb_link_health: kernel log not readable — sysfs-only mode "
                             "(add the service user to the 'systemd-journal' group for error counts)")
            self.klog_available = False
            return
        self.klog_available = True
        newest = since
        for line in lines:
            parsed = parse_klog_line(line)
            if not parsed:
                continue
            ts, kind, path = parsed
            if ts is not None:
                if ts <= since:
                    continue
                newest = max(newest, ts)
            self._count(kind, path, ts or now)
        self._klog_cursor = max(newest, since)
        self._check_burst(now)

    def _count(self, kind, path, t):
        if kind == "disconnect":
            self.counters["kernel_disconnects"][path] += 1
            return
        self.counters[kind][path] += 1
        if kind in ("tt", "cable", "enum", "overcurrent"):
            self.err_times.append(t)

    def _check_burst(self, now):
        while self.err_times and now - self.err_times[0] > BURST_WINDOW_S:
            self.err_times.popleft()
        n = len(self.err_times)
        if self.burst_raised_at and now - self.burst_raised_at > BURST_REARM_S and n < self.burst_n:
            self.burst_raised_at = None
        if n >= self.burst_n and self.burst_raised_at is None:
            self.burst_raised_at = now
            top = self.suspects(1)
            who = f" Worst offender: {top[0]['path']}." if top else ""
            self._event("error_burst", now, f"{n} USB protocol errors in {BURST_WINDOW_S:.0f}s — link degrading.{who}",
                        [top[0]["path"]] if top else [],
                        f"{n} USB errors in a minute — a drop is likely.{who}", "critical" if self.print_state == "printing" else "warn")

    # -- analysis --------------------------------------------------------------
    def suspects(self, limit=5):
        paths = set()
        for c in self.counters.values():
            paths |= set(c)
        rows = []
        for p in paths:
            drops = max(self.counters["sysfs_disconnects"][p], self.counters["kernel_disconnects"][p])
            tt, cable = self.counters["tt"][p], self.counters["cable"][p]
            enum, oc = self.counters["enum"][p], self.counters["overcurrent"][p]
            score = drops * 3 + min(tt, 200) * 0.1 + cable * 5 + enum * 3 + oc * 10
            if score <= 0:
                continue
            reasons = [HINTS[k] for k, v in (("cable", cable), ("tt", tt), ("enum", enum), ("overcurrent", oc)) if v]
            info = self.names.get(p)
            children = sorted(label(i) for q, i in self.names.items() if parent_of(q) == p)
            rows.append({"path": p, "device": label(info) if info else None, "is_hub": bool(info and info["is_hub"]),
                         "hub_tiers_deep": depth_of(p), "drops": drops, "protocol_errors": tt, "cable_errors": cable,
                         "enumeration_errors": enum, "overcurrent": oc, "score": round(score, 1),
                         "carries": children, "likely": reasons})
        return sorted(rows, key=lambda r: -r["score"])[:limit]

    def topology(self):
        def node(p):
            info = self.known.get(p) or self.names.get(p) or {"path": p}
            return {"path": p, "device": label(info), "present": p in self.known, "klipper_mcu": is_klipper_mcu(info),
                    "children": [node(q) for q in sorted(self.names) if parent_of(q) == p]}
        return [node(p) for p in sorted(self.names) if parent_of(p) is None]

    def status(self):
        self._load()
        return {"sysfs_devices": len(self.known), "kernel_log": {None: "untried", True: "readable",
                                                                     False: "unreadable (sysfs-only)"}[self.klog_available],
                "burst_threshold": self.burst_n, "errors_last_minute": len(self.err_times),
                "suspects": self.suspects(), "events": list(self.events)[:50], "topology": self.topology(),
                "pending_drops": [label(v["info"]) for v in self.pending.values()]}

    # -- hooks -----------------------------------------------------------------
    def poll(self):
        now = time.time()
        self.poll_sysfs(now)
        if now - self._last_klog >= KLOG_EVERY_S:
            self._last_klog = now
            self.poll_klog(now)
        if now - self._last_save >= SAVE_EVERY_S:
            self.save(now)


monitor = UsbLinkHealth()
_poller = Poller(monitor.poll, POLL_S, "usb-link-health")


def _tick(snap, ctx):
    monitor.print_state = snap.get("print_state")
    if os.environ.get("INDUS3D_USB_MONITOR", "1") != "0" and os.path.isdir(SYSFS):
        _poller.start()


def register_hooks(hooks) -> None:
    hooks.on("tick", _tick, priority=49)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_usb_link_health", __name__, url_prefix="/api/v1/plugins/usb_link_health")

    @bp.route("", methods=["GET"])
    def usb_status():
        return jsonify(monitor.status())

    app.register_blueprint(bp)
