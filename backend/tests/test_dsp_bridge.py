"""Tests for the DspBridge binary packet encoding, collision listener,
velocity metadata sending, and graceful no-op when the Rust binary is absent.

Run with:
    backend/.venv/bin/pytest backend/tests/test_dsp_bridge.py -v
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

# ── Constants matching dsp_bridge.py ─────────────────────────────────────────
_MAGIC       = b"IDX"
_SCALE       = 0.0039
_SAMPLE_FMT  = "<fhhhI"
_SAMPLE_SIZE = struct.calcsize(_SAMPLE_FMT)  # 14 bytes
_IN_PORT     = 3200
_COLL_PORT   = 3202
_META_PORT   = 3203


# ── Helper: decode one binary sample from a datagram ─────────────────────────

def _decode_binary_packet(data: bytes):
    """Return list of (ts, x_g, y_g, z_g) tuples decoded from an IDX packet."""
    assert data[:3] == _MAGIC, "Missing IDX magic"
    samples = []
    offset = 3
    while offset + _SAMPLE_SIZE <= len(data):
        ts, xi, yi, zi, _ = struct.unpack_from(_SAMPLE_FMT, data, offset)
        samples.append((ts, xi * _SCALE, yi * _SCALE, zi * _SCALE))
        offset += _SAMPLE_SIZE
    return samples


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Binary packet round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestBinaryPacketRoundTrip(unittest.TestCase):
    """send_adxl_binary() must produce a decodable IDX packet whose values
    round-trip through the ADC quantisation within ±_SCALE/2."""

    def setUp(self):
        # Import here so sys.path is already set by the test runner
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from workers.dsp_bridge import DspBridge
        self.bridge = DspBridge()

        # Patch the socket so we can capture what gets sent
        self._captured = []
        fake_sock = MagicMock()
        fake_sock.sendto.side_effect = lambda data, addr: self._captured.append((data, addr))
        self.bridge._out_sock = fake_sock
        self.bridge._available = True

    def test_magic_prefix(self):
        self.bridge.send_adxl_binary(0.1, -0.2, 0.05, t=1234.0)
        self.assertEqual(len(self._captured), 1)
        data, addr = self._captured[0]
        self.assertEqual(data[:3], _MAGIC)
        self.assertEqual(addr, ("127.0.0.1", _IN_PORT))

    def test_single_sample_size(self):
        self.bridge.send_adxl_binary(0.1, -0.2, 0.05, t=1234.0)
        data, _ = self._captured[0]
        # 3 magic + 14 sample = 17 bytes
        self.assertEqual(len(data), 3 + _SAMPLE_SIZE)

    def test_round_trip_values(self):
        x_in, y_in, z_in, t_in = 0.5, -0.25, 0.1, 100.0
        self.bridge.send_adxl_binary(x_in, y_in, z_in, t=t_in)
        data, _ = self._captured[0]
        samples = _decode_binary_packet(data)
        self.assertEqual(len(samples), 1)
        ts, x_out, y_out, z_out = samples[0]
        self.assertAlmostEqual(ts, t_in, places=4)
        # Quantisation error ≤ _SCALE/2
        self.assertAlmostEqual(x_out, x_in, delta=_SCALE / 2)
        self.assertAlmostEqual(y_out, y_in, delta=_SCALE / 2)
        self.assertAlmostEqual(z_out, z_in, delta=_SCALE / 2)

    def test_i16_clamping(self):
        """Values exceeding ±16g (±4096 counts) must be clamped to i16 range."""
        self.bridge.send_adxl_binary(200.0, -200.0, 0.0, t=0.0)
        data, _ = self._captured[0]
        _, ts, xi, yi, zi, _ = (None,) + struct.unpack_from(_SAMPLE_FMT, data, 3)
        self.assertEqual(xi, 32767)
        self.assertEqual(yi, -32768)

    def test_no_op_when_unavailable(self):
        self.bridge._available = False
        self.bridge.send_adxl_binary(1.0, 1.0, 1.0)
        self.assertEqual(len(self._captured), 0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Velocity metadata
# ─────────────────────────────────────────────────────────────────────────────

class TestVelocityMeta(unittest.TestCase):
    def setUp(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from workers.dsp_bridge import DspBridge
        self.bridge = DspBridge()
        self._captured = []
        fake_sock = MagicMock()
        fake_sock.sendto.side_effect = lambda data, addr: self._captured.append((data, addr))
        self.bridge._out_sock = fake_sock
        self.bridge._available = True

    def test_sends_correct_json(self):
        self.bridge.send_velocity_meta(50.0, 30.0, steps_mm=80.0)
        self.assertEqual(len(self._captured), 1)
        data, addr = self._captured[0]
        self.assertEqual(addr, ("127.0.0.1", _META_PORT))
        payload = json.loads(data.decode())
        self.assertAlmostEqual(payload["vx"], 50.0, places=3)
        self.assertAlmostEqual(payload["vy"], 30.0, places=3)
        self.assertAlmostEqual(payload["steps_mm"], 80.0, places=1)

    def test_no_op_when_unavailable(self):
        self.bridge._available = False
        self.bridge.send_velocity_meta(50.0, 30.0)
        self.assertEqual(len(self._captured), 0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Collision listener thread
# ─────────────────────────────────────────────────────────────────────────────

class TestCollisionListener(unittest.TestCase):
    """Inject a CollisionEvent JSON into a real UDP socket and verify that
    DspBridge._collision_listen_loop() picks it up and stores it."""

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_collision_event_stored(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from workers.dsp_bridge import DspBridge

        port = self._find_free_port()
        bridge = DspBridge()
        bridge._running = True

        # Wire up a real UDP socket on the free port
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.settimeout(1.0)
        bridge._coll_sock = sock

        # Patch the loop to use our port binding
        t = threading.Thread(target=bridge._collision_listen_loop, daemon=True)
        t.start()

        # Send a synthetic CollisionEvent
        event = {"timestamp": time.time(), "axis": "x", "peak_g": 4.2}
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(json.dumps(event).encode(), ("127.0.0.1", port))
        sender.close()

        # Wait for the listener to process it
        deadline = time.time() + 2.0
        while bridge.latest_collision is None and time.time() < deadline:
            time.sleep(0.05)

        bridge._running = False
        sock.close()

        self.assertIsNotNone(bridge.latest_collision)
        self.assertAlmostEqual(bridge.latest_collision["peak_g"], 4.2, places=5)
        self.assertEqual(bridge.latest_collision["axis"], "x")

    def test_invalid_json_ignored(self):
        """Malformed JSON must not crash the listener or update latest_collision."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from workers.dsp_bridge import DspBridge

        port = self._find_free_port()
        bridge = DspBridge()
        bridge._running = True

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.settimeout(0.5)
        bridge._coll_sock = sock

        t = threading.Thread(target=bridge._collision_listen_loop, daemon=True)
        t.start()

        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(b"not json {{{", ("127.0.0.1", port))
        sender.close()
        time.sleep(0.3)

        bridge._running = False
        sock.close()

        self.assertIsNone(bridge.latest_collision)


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Graceful no-op when binary absent
# ─────────────────────────────────────────────────────────────────────────────

class TestGracefulFallback(unittest.TestCase):
    """start() must not raise if the Rust binary does not exist."""

    def test_start_with_missing_binary(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from workers.dsp_bridge import DspBridge

        bridge = DspBridge()
        with patch("workers.dsp_bridge._DSP_BIN", "/nonexistent/path/indus3d-dsp"):
            bridge.start()  # must not raise

        self.assertFalse(bridge.available)
        self.assertFalse(bridge._running)

    def test_send_methods_no_op_when_unavailable(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from workers.dsp_bridge import DspBridge

        bridge = DspBridge()
        # Must not raise even when _available=False and _out_sock=None
        bridge.send_adxl_binary(1.0, 2.0, 3.0)
        bridge.send_adxl(1.0, 2.0, 3.0)
# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Rust resonance CSV analyser
# ─────────────────────────────────────────────────────────────────────────────

class TestRustResonanceAnalyser(unittest.TestCase):
    def test_analyse_csv_with_rust(self):
        import os
        import tempfile
        from core.shaper_tuner import analyse_csv_with_rust

        bin_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "dsp", "target", "release", "indus3d-dsp")
        )
        if not os.path.isfile(bin_path):
            self.skipTest("Rust binary indus3d-dsp not compiled yet (run cargo build --release)")

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("freq,psd_x,psd_y,psd_z\n")
            for freq in range(10, 100):
                # peak at 45 Hz
                px = 50.0 if freq == 45 else 1.0
                f.write(f"{freq}.0,{px},1.0,1.0\n")
            tmp_path = f.name

        try:
            res = analyse_csv_with_rust(tmp_path, "x")
            self.assertIsNotNone(res)
            self.assertEqual(res.get("axis"), "x")
            self.assertAlmostEqual(res.get("peak_hz", 0), 45.0, places=0)
            self.assertIn("shaper_type", res)
        finally:
            import os
            try:
                os.remove(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
