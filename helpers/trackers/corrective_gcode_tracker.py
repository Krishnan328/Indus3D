#!/usr/bin/env python3
"""Corrective G-code tracker for Indus3D (read-only, stdlib only).

Why this exists
---------------
Indus3D keeps its record of corrective G-code in memory only: the dashboard
sees the last ~10 corrections and ~20 commands, ``command_log`` /
``action_log`` stay empty for autopilot traffic, and when the auto-pilot is
off the quality controller computes but sends nothing at all. That makes
"Indus did not send what I expected" hard to investigate after the fact.

This tool polls the safe GET endpoints only (it never POSTs, so it can never
change the printer or the auto-pilot) and:

* ``--diagnose``  one-shot checklist explaining why corrective G-code is or
                  is not being sent right now (auto-pilot off, not printing,
                  M221 contention with the filament-sensor daemon, ...).
* ``--follow``    append every observed command / correction / state change
                  to a JSONL trail, with heartbeats and silence warnings.
* ``--summary F`` summarise a trail: commands per type, rate, silent gaps.

Exit codes for ``--diagnose``: 0 healthy, 1 warnings, 2 blocking problem.
"""

from __future__ import annotations

import argparse
import configparser
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

DEFAULT_URL = "http://127.0.0.1:5001"
DEFAULT_SENSOR_URL = "http://127.0.0.1:7126"
DEFAULT_OUTPUT = Path.home() / ".local/share/indus3d/tracker/corrective_gcode.jsonl"

AUTOPILOT_PATH = "/api/v1/twin/auto-pilot"
STATE_PATH = "/api/v1/twin/state"
ACTION_LOG_PATH = "/api/v1/twin/action/log?limit=20"
HEALTH_PATH = "/api/v1/health"

# Printing with the auto-pilot on but no corrective output for this long is
# reported as a silence warning (the loops are rate-limited to seconds).
SILENCE_WARN_SECONDS = 120.0


# ── HTTP ─────────────────────────────────────────────────────────────────────
def password_from_file(path: Path) -> str:
    """Read only INDUS3D_PASSWORD from an EnvironmentFile-style file."""
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "INDUS3D_PASSWORD" and value.strip():
            return value.strip().strip("'\"")
    raise ValueError("INDUS3D_PASSWORD not found in password file")


def make_getter(base: str, password: Optional[str], timeout: float = 4.0) -> Callable[[str], dict]:
    """GET-only JSON fetcher. The credential is only ever sent as a Bearer
    header to ``base`` and never written to the trail."""
    base = base.rstrip("/")

    def get(path: str) -> dict:
        req = urllib.request.Request(base + path, method="GET")
        if password:
            req.add_header("Authorization", f"Bearer {password}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return get


def safe(get: Callable[[str], dict], path: str) -> Tuple[Optional[object], Optional[str]]:
    try:
        return get(path), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 — report, never crash the tracker
        return None, f"{type(e).__name__}: {e}"


# ── Diagnose ─────────────────────────────────────────────────────────────────
OK, WARN, FAIL = "OK", "WARN", "FAIL"


def sensor_auto_flow_enabled(ini_path: Optional[Path]) -> Optional[bool]:
    if not ini_path or not ini_path.is_file():
        return None
    cp = configparser.ConfigParser()
    cp.read(ini_path)
    return cp.getboolean("features", "enable_auto_flow", fallback=False)


def diagnose(get: Callable[[str], dict], sensor_get: Optional[Callable[[str], dict]],
             sensor_ini: Optional[Path]) -> List[Tuple[str, str, str]]:
    """Return [(level, check, detail)]."""
    out: List[Tuple[str, str, str]] = []

    health, err = safe(get, HEALTH_PATH)
    if err:
        out.append((FAIL, "backend reachable", f"cannot reach Indus3D ({err})"))
        return out
    out.append((OK, "backend reachable", "health endpoint answered"))

    ap, err = safe(get, AUTOPILOT_PATH)
    autopilot = None
    if err:
        out.append((WARN, "auto-pilot state", f"unreadable ({err}); is auth enabled? use --password-file"))
    else:
        autopilot = bool(ap.get("auto_pilot_enabled"))
        if autopilot:
            out.append((OK, "auto-pilot", "enabled"))
        else:
            out.append((FAIL, "auto-pilot",
                        "DISABLED — the quality controller calculates but sends NO corrective "
                        "G-code. Enable it (dashboard, or POST /api/v1/twin/auto-pilot "
                        '{"enabled": true}).'))

    state, err = safe(get, STATE_PATH)
    printing = False
    if err or not isinstance(state, dict):
        out.append((WARN, "live state", f"unreadable ({err})"))
        state = {}
    else:
        ps = state.get("print_state", "unknown")
        printing = ps == "printing"
        if printing:
            out.append((OK, "print state", "printing"))
        else:
            out.append((WARN, "print state",
                        f"'{ps}' — corrections are only issued while printing"))
        quality = state.get("quality", {}) or {}
        active = quality.get("active", {}) or {}
        if active:
            out.append((OK, "controller values", ", ".join(
                f"{k}={active[k]}" for k in ("flow_pct", "speed_pct", "pa", "temp", "fan") if k in active)))
        n_corr = len(quality.get("corrections", []) or [])
        n_cmd = len(state.get("live_commands", []) or [])
        out.append((OK if (n_corr or n_cmd) else WARN, "recent output",
                    f"{n_corr} correction(s), {n_cmd} command(s) in the in-memory window"))

    log, err = safe(get, ACTION_LOG_PATH)
    if not err and isinstance(log, list) and not log:
        out.append((WARN, "action log",
                    "empty — autopilot traffic is not written to action_log/command_log; "
                    "run this tracker with --follow to keep a durable trail"))

    flow_sensor = sensor_auto_flow_enabled(sensor_ini)
    sensor_up = False
    if sensor_get is not None:
        s, err = safe(sensor_get, "/status")
        sensor_up = err is None
    if autopilot and (flow_sensor or sensor_up):
        out.append((WARN, "M221 contention",
                    "the filament-sensor daemon (auto-flow) and the Indus3D flow loop both "
                    "write M221; they will fight. Disable one: enable_auto_flow=false in "
                    "indus3d_sensor.ini, or leave the Indus3D flow loop for the sensor."))
    if printing and autopilot is False:
        out.append((FAIL, "diagnosis", "printing right now with auto-pilot OFF — nothing is being corrected"))
    return out


def print_report(rows: List[Tuple[str, str, str]]) -> int:
    worst = 0
    for level, check, detail in rows:
        print(f"[{level:<4}] {check}: {detail}")
        worst = max(worst, {OK: 0, WARN: 1, FAIL: 2}[level])
    return worst


# ── Follow ───────────────────────────────────────────────────────────────────
class Trail:
    """Append-only JSONL writer."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def write(self, kind: str, **fields) -> dict:
        rec = {"t": time.time(), "kind": kind, **fields}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        return rec


class Follower:
    def __init__(self, get: Callable[[str], dict], trail: Trail, now: Callable[[], float] = time.time):
        self.get, self.trail, self.now = get, trail, now
        self.seen_cmds: set = set()
        self.seen_corr: set = set()
        self.autopilot: Optional[bool] = None
        self.print_state: Optional[str] = None
        self.last_output_t: Optional[float] = None
        self.counts: Counter = Counter()
        self.silence_reported = False

    def poll_once(self) -> None:
        ap, err = safe(self.get, AUTOPILOT_PATH)
        if not err and isinstance(ap, dict):
            val = bool(ap.get("auto_pilot_enabled"))
            if val != self.autopilot:
                self.trail.write("autopilot", enabled=val)
                self.autopilot = val

        state, err = safe(self.get, STATE_PATH)
        if err or not isinstance(state, dict):
            self.trail.write("error", where="state", detail=err)
            return

        ps = state.get("print_state")
        if ps != self.print_state:
            self.trail.write("state", print_state=ps, previous=self.print_state)
            self.print_state = ps
            self.silence_reported = False
            if ps == "printing":
                self.last_output_t = self.now()

        for c in state.get("live_commands", []) or []:
            key = (c.get("ts"), c.get("text"))
            if key in self.seen_cmds:
                continue
            self.seen_cmds.add(key)
            text = str(c.get("text", ""))
            self.counts["commands"] += 1
            self.trail.write("command", text=text, ts=c.get("ts"),
                             source="qc" if text.startswith("[QC") else "other",
                             ok=not text.startswith("[QC FAIL]"))
            self.last_output_t = self.now()

        for c in (state.get("quality", {}) or {}).get("corrections", []) or []:
            key = (c.get("ts"), c.get("type"), c.get("value"))
            if key in self.seen_corr:
                continue
            self.seen_corr.add(key)
            self.counts[f"correction:{c.get('type')}"] += 1
            self.trail.write("correction", **{k: c.get(k) for k in ("ts", "type", "value", "reason")})
            self.last_output_t = self.now()

        # Bounded memory: only the in-memory windows can repeat.
        for s in (self.seen_cmds, self.seen_corr):
            if len(s) > 2000:
                s.clear()

        if (self.print_state == "printing" and self.autopilot and self.last_output_t is not None
                and self.now() - self.last_output_t > SILENCE_WARN_SECONDS and not self.silence_reported):
            self.trail.write("silence", seconds=round(self.now() - self.last_output_t, 1),
                             detail="printing with auto-pilot on but no corrective output")
            self.silence_reported = True

    def heartbeat(self) -> None:
        self.trail.write("heartbeat", autopilot=self.autopilot, print_state=self.print_state,
                         totals=dict(self.counts))


def follow(get, output: Path, interval: float, heartbeat_s: float,
           stop: Optional[Callable[[], bool]] = None) -> None:
    f = Follower(get, Trail(output))
    f.trail.write("start", output=str(output), interval=interval)
    last_hb = time.time()
    while not (stop and stop()):
        f.poll_once()
        if time.time() - last_hb >= heartbeat_s:
            f.heartbeat()
            last_hb = time.time()
        time.sleep(interval)


# ── Summary ──────────────────────────────────────────────────────────────────
def summarize(path: Path) -> dict:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cmds = [e for e in events if e["kind"] == "command"]
    kinds = Counter(e["kind"] for e in events)
    by_cmd = Counter((e.get("text", "").replace("[QC FAIL] ", "").replace("[QC] ", "").split() or ["?"])[0]
                     for e in cmds)
    span = (events[-1]["t"] - events[0]["t"]) if len(events) > 1 else 0.0
    return {
        "events": len(events),
        "span_seconds": round(span, 1),
        "event_kinds": dict(kinds),
        "commands_by_type": dict(by_cmd),
        "failed_commands": sum(1 for e in cmds if not e.get("ok", True)),
        "commands_per_minute": round(len(cmds) / (span / 60), 2) if span > 0 else 0.0,
        "silence_warnings": [e for e in events if e["kind"] == "silence"],
        "autopilot_changes": [{"t": e["t"], "enabled": e["enabled"]} for e in events if e["kind"] == "autopilot"],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--diagnose", action="store_true", help="one-shot checklist (default)")
    mode.add_argument("--follow", action="store_true", help="append observations to a JSONL trail")
    mode.add_argument("--summary", type=Path, metavar="TRAIL", help="summarise a JSONL trail")
    p.add_argument("--url", default=DEFAULT_URL, help="Indus3D base URL")
    p.add_argument("--password-file", type=Path, help="EnvironmentFile holding INDUS3D_PASSWORD")
    p.add_argument("--sensor-url", default=DEFAULT_SENSOR_URL, help="filament-sensor daemon URL ('' to skip)")
    p.add_argument("--sensor-ini", type=Path, help="indus3d_sensor.ini, to check enable_auto_flow")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--heartbeat", type=float, default=60.0)
    args = p.parse_args(argv)

    if args.summary:
        print(json.dumps(summarize(args.summary), indent=2))
        return 0

    password = password_from_file(args.password_file) if args.password_file else None
    get = make_getter(args.url, password)

    if args.follow:
        if not 0.2 <= args.interval <= 30:
            p.error("--interval must be 0.2–30 s")
        try:
            follow(get, args.output, args.interval, args.heartbeat)
        except KeyboardInterrupt:
            pass
        return 0

    sensor_get = make_getter(args.sensor_url, None, 2.0) if args.sensor_url else None
    return print_report(diagnose(get, sensor_get, args.sensor_ini))


if __name__ == "__main__":
    sys.exit(main())
