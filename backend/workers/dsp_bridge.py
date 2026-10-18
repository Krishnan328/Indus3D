"""DSP Bridge — connects the Rust indus3d-dsp binary to the Python backend.

Responsibilities:
  1. Start the Rust binary as a subprocess (skip gracefully if binary missing).
  2. Listen on UDP 3201 for 1-Hz processed JSON from Rust (slow-path spectral).
  3. Listen on UDP 3202 for instant CollisionEvent JSON from Rust (fast-path).
  4. Expose DspBridge.latest — the most recent {x, y, z} result dicts.
  5. Expose DspBridge.latest_collision — the most recent collision event or None.
  6. Provide send_adxl_binary(x, y, z, t) so the simulator can feed synthetic
     binary-format ADXL data into the Rust pipeline.
  7. Provide send_adxl(x, y, z, t) CSV fallback for backward compatibility.
  8. Provide send_velocity_meta(vx, vy, steps_mm) to feed velocity context to
     the Rust motor-step notch filter (UDP 3203).

Thread safety: send_adxl*() and send_velocity_meta() may be called from the
simulator thread; both UDP listener threads run as daemon threads. `latest` and
`latest_collision` are replaced atomically (dict re-assignment is GIL-protected
in CPython).

UDP port allocation
-------------------
  3200 — raw ADXL input   (Python → Rust, binary or CSV)
  3201 — slow-path output (Rust → Python, 1-Hz spectral JSON)
  3202 — fast-path output (Rust → Python, instant collision JSON)
  3203 — velocity meta    (Python → Rust, JSON {"vx":…, "vy":…, "steps_mm":…})
"""

from __future__ import annotations

import json
import logging
import math
import os
import socket
import struct
import subprocess
import threading
import time

_DSP_BIN = os.path.join(
    os.path.dirname(__file__), "..", "dsp", "target", "release", "indus3d-dsp"
)
_IN_PORT        = 3200   # Rust binary listens here for raw ADXL data
_OUT_PORT       = 3201   # Rust binary sends slow-path processed JSON here
_COLLISION_PORT = 3202   # Rust binary sends fast-path collision events here
_META_PORT      = 3203   # Rust binary listens here for velocity metadata

# Binary packet constants — must match Rust src/main.rs parse_binary_packet()
_MAGIC        = b"IDX"
_SCALE        = 0.0039   # g per raw ADC count (ADXL345 ±16g full-scale)
_SAMPLE_FMT   = "<fhhhI"  # f32 ts, i16 x, i16 y, i16 z, u32 padding = 14 bytes
_SAMPLE_SIZE  = struct.calcsize(_SAMPLE_FMT)  # 14

_EMPTY_AXIS = {"rms": 0.0, "peak_hz": 0.0, "kurtosis": 0.0,
               "magnitude": 0.0, "stiffness": 0.0, "torque_ripple": 0.0}


class DspBridge:
    """Singleton bridge between the Python backend and the Rust DSP pipeline."""

    def __init__(self):
        self.latest: dict | None = None           # {x: {...}, y: {...}, z: {...}}
        self.latest_collision: dict | None = None  # CollisionEvent or None
        self._proc: subprocess.Popen | None = None
        self._running = False
        self._out_sock: socket.socket | None = None    # sender to Rust :3200
        self._in_sock: socket.socket | None = None     # listener :3201 (spectral)
        self._coll_sock: socket.socket | None = None   # listener :3202 (collision)
        self._listener_thread: threading.Thread | None = None
        self._collision_thread: threading.Thread | None = None
        self._available = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        """Start the Rust binary and the UDP listeners. Safe to call multiple times."""
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
            # Sender socket — no binding needed (fires UDP to Rust :3200)
            self._out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Listener :3201 — 1-Hz slow-path spectral JSON from Rust
            self._in_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._in_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._in_sock.bind(("127.0.0.1", _OUT_PORT))
            self._in_sock.settimeout(1.0)

            # Listener :3202 — fast-path collision events from Rust
            self._coll_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._coll_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._coll_sock.bind(("127.0.0.1", _COLLISION_PORT))
            self._coll_sock.settimeout(1.0)
        except OSError as exc:
            # Vibration analysis is an optional capability. A busy or
            # unavailable UDP port must not prevent the printer dashboard
            # from starting.
            logging.warning(
                "⚠️  DSP UDP listener unavailable: %s — vibration analysis disabled", exc
            )
            self.stop()
            return

        self._running = True
        self._available = True

        self._listener_thread = threading.Thread(
            target=self._spectral_listen_loop, daemon=True, name="dsp-spectral"
        )
        self._listener_thread.start()

        self._collision_thread = threading.Thread(
            target=self._collision_listen_loop, daemon=True, name="dsp-collision"
        )
        self._collision_thread.start()

        logging.info(
            "📡 DSP UDP listeners started — spectral:%d, collision:%d",
            _OUT_PORT, _COLLISION_PORT,
        )

    def stop(self):
        """Terminate the Rust binary and stop the listener threads."""
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
        for sock in (self._in_sock, self._out_sock, self._coll_sock):
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        self._in_sock = None
        self._out_sock = None
        self._coll_sock = None

    def send_adxl_binary(self, x: float, y: float, z: float, t: float | None = None):
        """Send one ADXL sample as a binary IDX packet to the Rust pipeline.

        Format: magic b'IDX' + struct.pack('<fhhhI', ts, xi, yi, zi, 0)
        This matches parse_binary_packet() in Rust src/main.rs exactly.
        """
        if not self._available or not self._out_sock:
            return
        ts = t if t is not None else time.time()
        xi = max(-32768, min(32767, int(round(x / _SCALE))))
        yi = max(-32768, min(32767, int(round(y / _SCALE))))
        zi = max(-32768, min(32767, int(round(z / _SCALE))))
        try:
            msg = _MAGIC + struct.pack(_SAMPLE_FMT, ts, xi, yi, zi, 0)
            self._out_sock.sendto(msg, ("127.0.0.1", _IN_PORT))
        except OSError:
            pass  # socket closed during shutdown

    def send_adxl(self, x: float, y: float, z: float, t: float | None = None):
        """Legacy CSV-text fallback — kept for backward compatibility.

        The Rust binary auto-detects binary vs CSV per packet. Prefer
        send_adxl_binary() for new code paths.
        """
        if not self._available or not self._out_sock:
            return
        ts = t if t is not None else time.time()
        try:
            msg = f"{ts:.4f},{x:.5f},{y:.5f},{z:.5f}\n".encode()
            self._out_sock.sendto(msg, ("127.0.0.1", _IN_PORT))
        except OSError:
            pass  # socket closed during shutdown

    def send_velocity_meta(self, vx: float, vy: float, steps_mm: float = 80.0):
        """Push current axis velocity and steps-per-mm to the Rust notch filter.

        Rust uses this to compute step_freq_hz = |v_total| × steps_mm and
        notch out motor-step artefacts from the spectral output.
        """
        if not self._available or not self._out_sock:
            return
        try:
            meta = json.dumps({"vx": round(vx, 3), "vy": round(vy, 3),
                               "steps_mm": round(steps_mm, 1)}).encode()
            self._out_sock.sendto(meta, ("127.0.0.1", _META_PORT))
        except OSError:
            pass

    @property
    def available(self) -> bool:
        return self._available

    # ── Internal ───────────────────────────────────────────────────────────────

    def _spectral_listen_loop(self):
        """Receive 1-Hz slow-path spectral JSON from Rust (port 3201)."""
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

    def _collision_listen_loop(self):
        """Receive fast-path CollisionEvent JSON from Rust (port 3202)."""
        buf = bytearray(1024)
        while self._running:
            try:
                n, _ = self._coll_sock.recvfrom_into(buf)
                event = json.loads(buf[:n].decode())
                # Expected shape: {"timestamp": f64, "axis": str, "peak_g": f64}
                if isinstance(event, dict) and "timestamp" in event:
                    self.latest_collision = event
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
