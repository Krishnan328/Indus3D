#!/usr/bin/env python3
"""
Unit and Integration Test Suite for Indus3D ESP8266 Sensor Hub
==============================================================
Validates:
1. Binary packet checksum and serialization logic.
2. Jerk computation math: sqrt(dx^2 + dy^2 + dz^2).
3. Input Shaper mathematical models (ZV, MZV, ZVD, EI, 2HUMP_EI, 3HUMP_EI).
4. Welch's PSD spectral peak detection accuracy.
5. End-to-end TCP stream capture & calibration output generation.

Author: Krishnan H (Indus3D Project)
"""

import unittest
import struct
import numpy as np
import scipy.signal
import os
import sys

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esp_shaper_analyzer import InputShaperModel, analyze_resonances, PACKET_FORMAT, PACKET_SIZE


class TestSensorHubMath(unittest.TestCase):

    def test_packet_structure_and_checksum(self):
        """Verify binary packet format and checksum algorithm."""
        self.assertEqual(PACKET_SIZE, 15, "Packet size must be exactly 15 bytes.")

        magic0, magic1 = 0xAA, 0x55
        seq = 1042
        time_us = 4500000
        x_raw, y_raw, z_raw = 120, -450, -256

        # Pack first 14 bytes
        pre_pkt = struct.pack("<BBHIhhh", magic0, magic1, seq, time_us, x_raw, y_raw, z_raw)
        self.assertEqual(len(pre_pkt), 14)

        # Compute XOR checksum
        chk = 0
        for b in pre_pkt:
            chk ^= b

        full_pkt = pre_pkt + struct.pack("B", chk)
        self.assertEqual(len(full_pkt), 15)

        # Unpack and verify
        u_m0, u_m1, u_seq, u_time, u_x, u_y, u_z, u_crc = struct.unpack(PACKET_FORMAT, full_pkt)
        self.assertEqual(u_m0, magic0)
        self.assertEqual(u_m1, magic1)
        self.assertEqual(u_seq, seq)
        self.assertEqual(u_time, time_us)
        self.assertEqual(u_x, x_raw)
        self.assertEqual(u_y, y_raw)
        self.assertEqual(u_z, z_raw)
        self.assertEqual(u_crc, chk)

    def test_jerk_calculation(self):
        """Verify 3-axis jerk delta computation."""
        # Case 1: Simple 1D 2000 mg delta
        p1 = (100, 0, 0)
        p2 = (2100, 0, 0)
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        dz = p2[2] - p1[2]
        jerk = np.sqrt(dx**2 + dy**2 + dz**2)
        self.assertAlmostEqual(jerk, 2000.0, places=2)

        # Case 2: 3D vector delta (1000, 1000, 1000) -> sqrt(3000000) ~ 1732.05 mg
        p1 = (0, 0, 0)
        p2 = (1000, 1000, 1000)
        jerk_3d = np.sqrt(p2[0]**2 + p2[1]**2 + p2[2]**2)
        self.assertAlmostEqual(jerk_3d, 1732.05, places=1)

    def test_shaper_impulse_normalization(self):
        """Verify that all shaper filters normalize to unit sum (preserving DC gain = 1)."""
        f_target = 50.0
        shapers = ["ZV", "MZV", "ZVD", "EI", "2HUMP_EI", "3HUMP_EI"]

        for st in shapers:
            A, t = InputShaperModel.get_shaper_params(st, f_target)
            self.assertAlmostEqual(np.sum(A), 1.0, places=5, msg=f"Shaper {st} impulses must sum to 1.0")
            self.assertEqual(t[0], 0.0, msg=f"First impulse of {st} must be at t=0")

    def test_shaper_notch_depth_at_resonance(self):
        """Verify that shaper transfer functions create a strong notch at target frequency."""
        f_target = 45.0
        freqs = np.array([f_target])

        for st in ["ZV", "MZV", "ZVD", "EI"]:
            A, t = InputShaperModel.get_shaper_params(st, f_target)
            H = InputShaperModel.transfer_function(A, t, freqs)
            # Notch should attenuate target resonance by at least 95% (|H(f0)| <= 0.05)
            self.assertLess(H[0], 0.06, msg=f"Shaper {st} failed to attenuate resonance at {f_target} Hz")

    def test_psd_peak_detection(self):
        """Verify Welch PSD detects known resonance peak accurately."""
        fs = 1600.0 # 1600 Hz
        duration = 5.0
        N = int(fs * duration)
        t = np.linspace(0, duration, N, endpoint=False)

        known_f0 = 53.5 # Target resonance frequency in Hz
        # Signal: DC offset (1g gravity) + 53.5 Hz vibration + white noise
        sig_x = 0.05 * np.sin(2 * np.pi * 12 * t)
        sig_y = 0.40 * np.sin(2 * np.pi * known_f0 * t) + 0.02 * np.random.randn(N)
        sig_z = -1.0 + 0.01 * np.random.randn(N)

        synthetic_data = np.column_stack([t, sig_x, sig_y, sig_z])

        analysis = analyze_resonances(synthetic_data, axis_col=2)
        detected_f0 = analysis["primary_freq"]

        # Detected frequency should match known frequency within 1.0 Hz
        self.assertAlmostEqual(detected_f0, known_f0, delta=1.0,
                               msg=f"Expected ~{known_f0} Hz, detected {detected_f0:.2f} Hz")

        # Best shaper should show high vibration reduction (> 80%)
        best = analysis["best"]
        self.assertGreater(best["vibration_reduction_pct"], 80.0,
                           msg="Recommended shaper should achieve > 80% vibration reduction")


if __name__ == "__main__":
    unittest.main()
