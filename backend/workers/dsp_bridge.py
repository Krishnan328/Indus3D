"""DSP Bridge — connects the Rust indus3d-dsp binary to the Python backend.

Responsibilities:
  1. Start the Rust binary as a subprocess (skip gracefully if binary missing).
  2. Listen on UDP 3201 for 1-Hz processed JSON from Rust.
  3. Expose DspBridge.latest — the most recent {x, y, z} result dicts.
  4. Provide send_adxl(x, y, z) so the simulator can feed synthetic data in.

Thread safety: send_adxl() may be called from the simulator thread;
the UDP listener runs on its own daemon thread. `latest` is replaced
atomically (dict re-assignment is GIL-protected in CPython).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import time

_DSP_BIN = os.path.join(
    os.path.dirname(__file__), "..", "dsp", "target", "release", "indus3d-dsp"
)
_IN_PORT  = 3200   # Rust binary listens here for raw ADXL CSV data
_OUT_PORT = 3201   # Rust binary sends processed JSON here

_EMPTY_AXIS = {"rms": 0.0, "peak_hz": 0.0, "kurtosis": 0.0,
               "magnitude": 0.0, "stiffness": 0.0, "torque_ripple": 0.0}


class DspBridge:
    """Singleton bridge between the Python backend and the Rust DSP pipeline."""

    def __init__(self):
        self.latest: dict | None = None  # {x: {...}, y: {...}, z: {...}}
        self._proc: subprocess.Popen | None = None
        self._running = False
        self._out_sock: socket.socket | None = None
        self._in_sock: socket.socket | None = None
        self._listener_thread: threading.Thread | None = None
        self._available = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        """Start the Rust binary and the UDP listener. Safe to call multiple times."""
        if self._running:
            return

        bin_path = os.path.abspath(_DSP_BIN)
        if not os.path.isfile(bin_path):
            logging.warning(
                "⚠️  DSP binary not found at %s — vibration analysis disabled.\n"
                "   Run: cd backend/dsp && cargo build --release",
                bin_path,
            )
            return

        try:
            self._proc = subprocess.Popen(
                [bin_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info("🦀 DSP pipeline started (pid %d)", self._proc.pid)
        except OSError as e:
            logging.warning("⚠️  Failed to start DSP binary: %s", e)
            return

        try:
            # Socket for sending raw ADXL data TO Rust (port 3200)
            self._out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Socket for receiving processed JSON FROM Rust (port 3201)
            self._in_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._in_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._in_sock.bind(("127.0.0.1", _OUT_PORT))
            self._in_sock.settimeout(1.0)
        except OSError as exc:
            # Vibration analysis is an optional capability. A busy or
            # unavailable UDP port must not prevent the printer dashboard
            # from starting.
            logging.warning("⚠️  DSP UDP listener unavailable: %s — vibration analysis disabled", exc)
            self.stop()
            return

        self._running = True
        self._available = True

        self._listener_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="dsp-listener"
        )
        self._listener_thread.start()
        logging.info("📡 DSP UDP listener started on port %d", _OUT_PORT)

    def stop(self):
        """Terminate the Rust binary and stop the listener thread."""
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            logging.info("🛑 DSP pipeline stopped")
        for sock in (self._in_sock, self._out_sock):
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        self._in_sock = None
        self._out_sock = None

    def send_adxl(self, x: float, y: float, z: float, t: float | None = None):
        """Send a single ADXL sample to the Rust binary.

        Call ~32 times per 10 Hz tick to approximate a 320 Hz feed rate
        into the Rust 3200 Hz window (Rust buffers samples across ticks).
        """
        if not self._available or not self._out_sock:
            return
        ts = t if t is not None else time.time()
        try:
            msg = f"{ts:.4f},{x:.5f},{y:.5f},{z:.5f}\n".encode()
            self._out_sock.sendto(msg, ("127.0.0.1", _IN_PORT))
        except OSError:
            pass  # socket closed during shutdown

    @property
    def available(self) -> bool:
        return self._available

    # ── Internal ───────────────────────────────────────────────────────────────

    def _listen_loop(self):
        buf = bytearray(4096)
        while self._running:
            try:
                n, _ = self._in_sock.recvfrom_into(buf)
                payload = json.loads(buf[:n].decode())
                self.latest = {
                    "x": _normalise_axis(payload.get("x", {})),
                    "y": _normalise_axis(payload.get("y", {})),
                    "z": _normalise_axis(payload.get("z", {})),
                }
            except socket.timeout:
                pass
            except (json.JSONDecodeError, OSError):
                pass


def _normalise_axis(d: dict) -> dict:
    """Map Rust field names to canonical Python names."""
    return {
        "rms":           float(d.get("rms",            0.0)),
        "peak_hz":       float(d.get("hz",             0.0)),
        "kurtosis":      float(d.get("kurtosis",       0.0)),
        "magnitude":     float(d.get("mag",            0.0)),
        "stiffness":     float(d.get("stiffness",      0.0)),
        "torque_ripple": float(d.get("torque_ripple",  0.0)),
    }


# Module-level singleton used by simulator.py and main.py
dsp_bridge = DspBridge()
