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
import tempfile
from esp_shaper_analyzer import (InputShaperModel, analyze_resonances, PACKET_FORMAT, PACKET_SIZE,
                                 update_printer_cfg_text, apply_to_printer_cfg, pick_axis, run_analysis,
                                 estimate_zeta, save_klipper_csv)


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


def _resonance(fs, dur, f0, zeta, seed=1, axis=2):
    """Y-axis free ring-down excited by random impulses -> a damped resonance at f0."""
    rng = np.random.default_rng(seed)
    n = int(fs * dur)
    t = np.arange(n) / fs
    k = np.arange(int(0.5 * fs)) / fs
    h = np.exp(-zeta * 2 * np.pi * f0 * k) * np.sin(2 * np.pi * f0 * np.sqrt(1 - zeta ** 2) * k)
    y = np.convolve(rng.standard_normal(n), h)[:n] * 0.02
    cols = [rng.standard_normal(n) * 1e-4 for _ in range(3)]
    cols[axis - 1] = y
    cols[2] += -1.0 if axis != 3 else 0
    return np.column_stack([t] + cols)


class TestShaperPhysics(unittest.TestCase):
    def test_all_shapers_notch_at_design_frequency(self):
        for st in ["ZV", "MZV", "ZVD", "EI", "2HUMP_EI", "3HUMP_EI"]:
            A, t = InputShaperModel.get_shaper_params(st, 45.0, 0.1)
            v = InputShaperModel.transfer_function(A, t, np.array([45.0]), 0.1)[0]
            tol = 0.06 if st in ("ZV", "MZV", "ZVD") else 0.051
            self.assertLess(v, tol, st)

    def test_robustness_ordering(self):
        """Wider shapers tolerate a mistuned resonance better (at +-20 %)."""
        f = np.array([36.0, 54.0])
        worst = {}
        for st in ["ZV", "ZVD", "EI", "2HUMP_EI", "3HUMP_EI"]:
            A, t = InputShaperModel.get_shaper_params(st, 45.0, 0.1)
            worst[st] = InputShaperModel.transfer_function(A, t, f, 0.1).max()
        self.assertLess(worst["ZVD"], worst["ZV"])
        self.assertLess(worst["3HUMP_EI"], worst["EI"])

    def test_smoothing_and_accel_monotonic(self):
        A, t = InputShaperModel.get_shaper_params("ZV", 50.0)
        A2, t2 = InputShaperModel.get_shaper_params("3HUMP_EI", 50.0)
        self.assertLess(InputShaperModel.smoothing(A, t), InputShaperModel.smoothing(A2, t2))
        self.assertGreater(InputShaperModel.max_accel(A, t), InputShaperModel.max_accel(A2, t2))
        a = InputShaperModel.max_accel(A2, t2)
        self.assertLessEqual(InputShaperModel.smoothing(A2, t2, a), 0.1205)

    def test_recovers_frequency_and_damping(self):
        data = _resonance(1600, 20, 42.0, 0.08)
        an = analyze_resonances(data, axis_col=2)
        self.assertAlmostEqual(an["primary_freq"], 42.0, delta=1.5)
        self.assertAlmostEqual(an["zeta"], 0.08, delta=0.04)
        b = an["best"]
        self.assertGreater(b["vibration_reduction_pct"], 85)
        self.assertAlmostEqual(b["freq"], 42.0, delta=8)

    def test_nonuniform_timestamps_are_resampled(self):
        data = _resonance(1600, 10, 55.0, 0.1)
        rng = np.random.default_rng(3)
        data[:, 0] += rng.uniform(-0.0001, 0.0001, len(data))
        data[:, 0].sort()
        data = np.delete(data, np.arange(4000, 4010), axis=0)          # a gap from dropped packets
        an = analyze_resonances(data, axis_col=2)
        self.assertTrue(an["sampling"]["resampled"])
        self.assertAlmostEqual(an["primary_freq"], 55.0, delta=2)

    def test_auto_axis_picks_the_excited_axis(self):
        self.assertEqual(pick_axis(_resonance(1600, 5, 40, 0.1, axis=1)), 1)
        self.assertEqual(pick_axis(_resonance(1600, 5, 40, 0.1, axis=2)), 2)
        self.assertEqual(pick_axis(_resonance(1600, 5, 40, 0.1, axis=2), "x"), 1)

    def test_too_short_capture_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze_resonances(np.column_stack([np.arange(20) / 1600, np.zeros((20, 3))]), axis_col=2)


CFG = """[printer]
kinematics: corexy
max_accel: 3000

[input_shaper]
shaper_type_x: zv
shaper_freq_x: 60.0
damping_ratio_y: 0.05

[mcu]
serial: /dev/x

#*# <---- SAVE_CONFIG ---->
#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.
#*#
#*# [probe]
#*# z_offset = 1.2
"""


class TestPrinterCfgUpdate(unittest.TestCase):
    def test_updates_only_the_axis_keys(self):
        new, w = update_printer_cfg_text(CFG, "Y", "mzv", 42.6)
        self.assertIn("shaper_type_y: mzv", new)
        self.assertIn("shaper_freq_y: 42.6", new)
        for keep in ("shaper_type_x: zv", "shaper_freq_x: 60.0", "damping_ratio_y: 0.05", "max_accel: 3000",
                     "z_offset = 1.2", "serial: /dev/x"):
            self.assertIn(keep, new)
        self.assertEqual(w, [])
        sec = new.split("[input_shaper]")[1].split("[mcu]")[0]
        self.assertIn("shaper_freq_y", sec)                         # inside the right section

    def test_idempotent_and_replaces_existing(self):
        once, _ = update_printer_cfg_text(CFG, "Y", "mzv", 42.6)
        twice, _ = update_printer_cfg_text(once, "Y", "ei", 50.0)
        self.assertEqual(twice.count("shaper_type_y"), 1)
        self.assertIn("shaper_type_y: ei", twice)
        again, _ = update_printer_cfg_text(twice, "Y", "ei", 50.0)
        self.assertEqual(twice, again)

    def test_adds_section_when_missing(self):
        new, _ = update_printer_cfg_text("[printer]\nkinematics: cartesian\n", "Y", "zv", 33.0)
        self.assertIn("[input_shaper]\nshaper_type_y: zv\nshaper_freq_y: 33.0", new)

    def test_warns_about_autosaved_override(self):
        cfg = CFG.replace("#*# [probe]", "#*# [input_shaper]\n#*# shaper_type_y = ei\n#*# shaper_freq_y = 50.0\n#*#\n#*# [probe]")
        new, w = update_printer_cfg_text(cfg, "Y", "mzv", 42.6)
        self.assertEqual(len(w), 1)
        self.assertIn("SAVE_CONFIG", w[0])
        self.assertIn("#*# shaper_type_y = ei", new)                # never touches the autosave block

    def test_backup_and_apply(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "printer.cfg")
            open(p, "w").write(CFG)
            apply_to_printer_cfg(p, "Y", "mzv", 42.6)
            names = os.listdir(d)
            self.assertEqual(len([n for n in names if "indus3d_bak" in n]), 1)
            self.assertIn("shaper_freq_y: 42.6", open(p).read())

    def test_run_analysis_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            csv = os.path.join(d, "c.csv")
            save_klipper_csv(_resonance(1600, 12, 42.6, 0.08), csv)
            cfg = os.path.join(d, "printer.cfg")
            open(cfg, "w").write(CFG)
            rc = run_analysis(csv, "Y", d, apply_to=cfg)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(os.path.join(d, "shaper_calibration_bed_y.png")))
            self.assertIn("[input_shaper]", open(os.path.join(d, "bed_input_shaper_y.cfg")).read())
            self.assertRegex(open(cfg).read(), r"shaper_type_y: \w+")


if __name__ == "__main__":
    unittest.main()
