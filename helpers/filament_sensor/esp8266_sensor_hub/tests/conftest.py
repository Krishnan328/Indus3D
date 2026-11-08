"""Shared fixtures: a software model of the hub on the far end of a fake serial port."""
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hub_protocol as hp  # noqa: E402


class FakeHub:
    """Speaks the hub's serial protocol (mirrors firmware/src/main.cpp), including the baud switch
    for shaper sessions: bytes sent at a baud the host is not listening at arrive as garbage."""

    def __init__(self, baud=115200):
        self.baudrate = baud               # the HOST side of the port
        self.hub_baud = 115200             # what the ESP currently transmits at
        self.segments = []                 # [(required_baud, bytearray)]
        self.written = []
        self.lock = threading.Lock()
        self.is_open = True
        self.latched = False
        self.threshold = 2000
        self.uptime = 100
        self.drop_packets = 0              # simulate serial overruns during a capture
        self.silent = False                # simulate an old firmware that ignores commands
        self.fail_reads = 0
        self.max_serial_rate = None

    # -- host-facing serial API ------------------------------------------------------------
    @property
    def in_waiting(self):
        with self.lock:
            return sum(len(b) - pos for _, b, pos in self.segments)

    def _take(self, n, stop_at_newline=False):
        """Up to n bytes from the queued segments. Bytes of a segment sent at a baud the host is not
        listening at are delivered as noise (0xFF), like a real UART mis-sampling them."""
        out = bytearray()
        with self.lock:
            while self.segments and len(out) < n:
                seg = self.segments[0]                    # [required_baud, bytearray, read_offset]
                need, buf, pos = seg
                if pos >= len(buf):
                    self.segments.pop(0)
                    continue
                end = min(len(buf), pos + (n - len(out)))
                if stop_at_newline:
                    nl = buf.find(b"\n", pos, end)
                    if nl >= 0:
                        end = nl + 1
                chunk = bytes(buf[pos:end]) if self.baudrate == need else b"\xff" * (end - pos)
                seg[2] = end
                out += chunk
                if stop_at_newline and chunk.endswith(b"\n") and self.baudrate == need:
                    break
                if stop_at_newline and self.baudrate != need and end > pos and buf[end - 1:end] == b"\n":
                    break
        return bytes(out)

    def readline(self):
        if self.fail_reads:
            self.fail_reads -= 1
            raise OSError("device disconnected")
        data = self._take(4096, stop_at_newline=True)
        if not data:
            time.sleep(0.002)
        return data

    def read(self, n=1):
        data = self._take(max(1, n))
        if not data:
            time.sleep(0.002)
        return data

    def reset_input_buffer(self):
        with self.lock:
            self.segments.clear()

    def flush(self):
        pass

    def close(self):
        self.is_open = False

    def write(self, data: bytes):
        for line in data.decode().splitlines():
            self.written.append(line)
            if not self.silent:
                self._on_command(line.strip())
        return len(data)

    # -- hub behaviour -------------------------------------------------------------------------
    def push_text(self, text, baud=None):
        with self.lock:
            self.segments.append([baud or self.hub_baud, bytearray(text.encode()), 0])

    def push_telemetry(self, **kw):
        d = {"bed_accel": {"x_mg": -309, "y_mg": -395, "z_mg": -848, "jerk_mg": 7},
             "chamber": {"temp_c": 26.0, "humidity_pct": 45.5, "pressure_hpa": 1007.3},
             "crash_detected": self.latched, "crash_threshold_mg": self.threshold,
             "adxl_ok": True, "bme_ok": True, "uptime_sec": self.uptime}
        d.update(kw)
        self.push_text(json.dumps(d) + "\n")

    def push_crash_alert(self, jerk=2450, accel=(-420, 1850, -910)):
        self.latched = True
        self.push_text("// Klipper: BED_CRASH_DETECTED jerk=%d mg (accel=[%+d, %+d, %+d] mg) -> Auto-pausing print!\n"
                       % (jerk, *accel))

    def _on_command(self, cmd):
        parts = cmd.split()
        if not parts:
            return
        name = parts[0].upper()
        if name == "PING":
            self.push_text("PONG\n")
        elif name == "RESET_CRASH":
            self.latched = False
            self.push_text("// CRASH_RESET\n")
        elif name == "SET_CRASH_THRESHOLD":
            try:
                v = int(parts[1])
            except (IndexError, ValueError):
                return self.push_text("// ERROR: SET_CRASH_THRESHOLD <mg>\n")
            if not 500 <= v <= 8000:
                return self.push_text("// ERROR: threshold must be 500-8000 mg\n")
            self.threshold = v
            self.push_text(f"// CRASH_THRESHOLD_UPDATED: {v} mg\n")
        elif name == "START_SHAPER":
            self._start_shaper(parts[1:])
        elif name == "STOP_SHAPER":
            pass

    def _start_shaper(self, args):
        dur = int(args[0]) if args else 5
        req = int(args[1]) if len(args) > 1 else 1600
        baud = int(args[2]) if len(args) > 2 else 0
        link = baud if baud in (230400, 460800, 921600) else 115200
        cap = int(link / 10 * 0.85 / 15)
        rate = next(r for r in (3200, 1600, 800, 400, 200) if r <= req and r <= cap) if req >= 200 else 200
        n = dur * rate
        self.push_text(f"// SHAPER_SESSION_STARTED: duration={dur} s, rate={rate} Hz, baud={link}\n", baud=115200)
        frames = bytearray()
        sent = 0
        for i in range(n):
            if self.drop_packets and i % self.drop_packets == 0:
                continue
            t_us = int(i * 1e6 / rate)
            # 41 Hz resonance on Y, tiny noise on the others
            import math
            y = int(900 * math.sin(2 * math.pi * 41.0 * i / rate))
            frames += hp.pack_frame(i, t_us, 3, y, -256)
            sent += 1
        self.push_text("", baud=link)
        with self.lock:
            self.segments[-1][1].extend(frames)
            self.segments[-1][1].extend(f"\n// SHAPER_SESSION_ENDED: collected {sent} samples\n".encode())
        self.hub_baud = 115200               # the hub restores its baud after the ENDED marker


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture
def clock():
    class C:
        t = 1_000_000.0

        def __call__(self):
            return self.t
    return C()


class MoonrakerStub:
    """Records every call the daemon makes to Moonraker."""

    def __init__(self, state="printing"):
        self.state = state
        self.calls = []
        self.fail = False

    def __call__(self, method, url, body=None, timeout=2.0):
        self.calls.append((method, url.split("7125")[-1], body))
        if self.fail:
            raise OSError("connection refused")
        if "print_stats" in url:
            return {"result": {"status": {"print_stats": {"state": self.state}}}}
        return {"result": "ok"}


@pytest.fixture
def moon():
    return MoonrakerStub()
