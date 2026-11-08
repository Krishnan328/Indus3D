#!/usr/bin/env python3
"""
Indus3D ESP8266 input-shaper resonance analyzer (bed / Y axis)
==============================================================
Turns a high-rate accelerometer capture from the bed sensor hub into an input-shaper
recommendation:

  1. Welch power spectral density on the detrended signal, uniformly resampled first (the hub's
     timestamps are read times and jitter), band 5-120 Hz.
  2. Resonance peak f_peak and damping ratio zeta from the half-power bandwidth.
  3. The six Klipper shaper families (ZV, MZV, ZVD, EI, 2HUMP_EI, 3HUMP_EI) as impulse
     sequences (A_i, t_i), their exact residual-vibration response

        V(w) = exp(-zeta w t_N) * sqrt( (sum A_i e^{zeta w t_i} cos(w_d t_i))^2
                                      + (sum A_i e^{zeta w t_i} sin(w_d t_i))^2 )

  4. For every family a scan of the shaper frequency; the choice minimises
     smoothing x (vibr^1.5 + 0.2 vibr + 0.01), the trade-off Klipper itself uses, evaluated over
     zeta in {0.075, 0.1, 0.15} so the result is not tuned to one damping guess.
  5. Maximum acceleration from the smoothing limit (0.12 mm at scv = 5 mm/s, as in Klipper's
     docs), NOT from a rule of thumb.
  6. A plot, a config snippet, and optionally a safe in-place update of [input_shaper] in
     printer.cfg (backup first; refuses to be silently overridden by an auto-saved section).

Shaper definitions are the published textbook forms (Singer & Seering; Singhose et al.) with the
usual damping correction. Klipper's own SHAPER_CALIBRATE uses refined coefficient fits for EI and
the hump shapers, so figures can differ slightly: treat the result as a strong recommendation, and
prefer Klipper's tools whenever an accelerometer can be attached to the toolhead.
"""

import argparse
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_protocol as hp  # noqa: E402

PACKET_FORMAT = hp.PACKET_FORMAT
PACKET_SIZE = hp.PACKET_SIZE
SCALE_G_PER_LSB = hp.SCALE_G_PER_LSB
GRAVITY_MM_S2 = hp.GRAVITY_MM_S2

SHAPER_TYPES = ["ZV", "MZV", "ZVD", "EI", "2HUMP_EI", "3HUMP_EI"]
# Lowest frequency worth testing for each shaper (below it the smoothing is impractical)
MIN_SHAPER_FREQ = {"ZV": 21.0, "MZV": 23.0, "ZVD": 29.0, "EI": 29.0, "2HUMP_EI": 39.0, "3HUMP_EI": 48.0}
V_TOL = 0.05                       # EI vibration tolerance (5 %)
BAND_HZ = (5.0, 120.0)
TEST_ZETAS = (0.075, 0.10, 0.15)
DEFAULT_ZETA = 0.10
TARGET_SMOOTHING_MM = 0.12
DEFAULT_SCV = 5.0
REFERENCE_ACCEL = 5000.0


class InputShaperModel:
    """Impulse-sequence models of the Klipper input shapers."""

    @staticmethod
    def get_shaper_params(shaper_type, f_shaper, damping_ratio=DEFAULT_ZETA, v_tol=V_TOL) -> Tuple[np.ndarray, np.ndarray]:
        """(amplitudes, times) of the shaper, amplitudes normalised to sum 1."""
        st = shaper_type.upper()
        z = damping_ratio
        df = math.sqrt(1.0 - z * z)
        K = math.exp(-z * math.pi / df)
        td = 1.0 / (f_shaper * df)                        # damped period

        if st == "ZV":
            A, t = [1.0, K], [0.0, 0.5 * td]
        elif st == "ZVD":
            A, t = [1.0, 2.0 * K, K ** 2], [0.0, 0.5 * td, td]
        elif st == "MZV":
            Km = math.exp(-0.75 * z * math.pi / df)
            A, t = [1.0, math.sqrt(2.0) * Km, Km ** 2], [0.0, 0.375 * td, 0.75 * td]
        elif st == "EI":
            a = [(1 + v_tol) / 4, (1 - v_tol) / 2, (1 + v_tol) / 4]
            A, t = [a[i] * K ** i for i in range(3)], [0.0, 0.5 * td, td]
        elif st == "2HUMP_EI":
            v2 = v_tol ** 2
            X = (v2 * (math.sqrt(1 - v2) + 1)) ** (1.0 / 3.0)
            a1 = (3 * X * X + 2 * X + 3 * v2) / (16 * X)
            a = [a1, 0.5 - a1, 0.5 - a1, a1]
            A, t = [a[i] * K ** i for i in range(4)], [0.0, 0.5 * td, td, 1.5 * td]
        elif st == "3HUMP_EI":
            a1 = (1 + 3 * v_tol + 2 * math.sqrt(2 * v_tol * (v_tol + 1))) / 16
            a = [a1, (1 - v_tol) / 4, (1 + v_tol) / 2 - 2 * a1, (1 - v_tol) / 4, a1]
            A, t = [a[i] * K ** i for i in range(5)], [0.0, 0.5 * td, td, 1.5 * td, 2.0 * td]
        else:
            raise ValueError(f"Unknown shaper type: {shaper_type}")
        A = np.array(A, dtype=float)
        return A / A.sum(), np.array(t, dtype=float)

    @staticmethod
    def transfer_function(A, t, freqs, damping_ratio=DEFAULT_ZETA):
        """Residual vibration ratio V(f) of an underdamped oscillator for impulses (A, t)."""
        freqs = np.asarray(freqs, dtype=float)
        omega = 2.0 * np.pi * freqs
        omega_d = omega * math.sqrt(1.0 - damping_ratio ** 2)
        C = np.zeros_like(freqs)
        S = np.zeros_like(freqs)
        for a_i, t_i in zip(A, t):
            w = a_i * np.exp(damping_ratio * omega * t_i)
            C += w * np.cos(omega_d * t_i)
            S += w * np.sin(omega_d * t_i)
        return np.exp(-damping_ratio * omega * t[-1]) * np.sqrt(C ** 2 + S ** 2)

    @staticmethod
    def smoothing(A, t, accel=REFERENCE_ACCEL, scv=DEFAULT_SCV) -> float:
        """Toolpath smoothing (mm) the shaper introduces on 90 and 180 degree corners at `accel`."""
        half = accel * 0.5
        inv_d = 1.0 / float(np.sum(A))
        ts = float(np.sum(A * t)) * inv_d                # the shaper's net time shift
        off90 = off180 = 0.0
        for a_i, t_i in zip(A, t):
            dt = t_i - ts
            if t_i >= ts:
                off90 += a_i * (scv + half * dt) * dt
            off180 += a_i * half * dt * dt
        return max(off90 * inv_d * math.sqrt(2.0), off180 * inv_d)

    @classmethod
    def max_accel(cls, A, t, scv=DEFAULT_SCV, target=TARGET_SMOOTHING_MM) -> int:
        """Largest acceleration whose smoothing stays within `target` mm (bisection)."""
        lo, hi = 100.0, 100000.0
        if cls.smoothing(A, t, hi, scv) <= target:
            return int(hi)
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if cls.smoothing(A, t, mid, scv) <= target:
                lo = mid
            else:
                hi = mid
        return int(round(lo, -1))

    @staticmethod
    def shaper_accel_factor(shaper_type):
        """Rough rule of thumb (max_accel ~ factor * f). Kept for compatibility; the analysis
        uses `max_accel`, which follows from the smoothing limit."""
        return {"ZV": 105.0, "MZV": 75.0, "ZVD": 52.0, "EI": 50.0,
                "2HUMP_EI": 35.0, "3HUMP_EI": 25.0}.get(shaper_type.upper(), 50.0)


# ── signal processing ────────────────────────────────────────────────────────────────
def unpack_binary_frames(raw_bytes):
    """Raw hub bytes -> numpy array [[t_s, x_g, y_g, z_g], ...] (or None)."""
    samples, stats = hp.unpack_frames(bytes(raw_bytes))
    print(f"[PARSER] decoded {stats['packets']} frames "
          f"({stats['bad_checksum']} bad checksum, {stats['lost_packets']} lost, {stats['resyncs']} resyncs)")
    return np.array(samples) if samples else None


def load_csv_data(csv_path):
    """Klipper-format CSV (time,accel_x,accel_y,accel_z)."""
    print(f"[CSV] loading {csv_path}")
    data = np.genfromtxt(csv_path, delimiter=",", skip_header=1)
    if data.ndim != 2 or data.shape[1] < 4:
        raise ValueError("expected at least 4 columns: time,accel_x,accel_y,accel_z")
    return data[:, :4]


def save_klipper_csv(data, output_path):
    np.savetxt(output_path, data, delimiter=",", header="time,accel_x,accel_y,accel_z", comments="",
               fmt="%.6f,%.5f,%.5f,%.5f")
    print(f"[CSV] saved {output_path}")


def resample_uniform(t: np.ndarray, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray, Dict]:
    """Interpolate onto a uniform grid at the median sample rate. Welch assumes uniform spacing,
    and the hub's timestamps are read times with jitter (and gaps when the serial link drops bytes)."""
    dts = np.diff(t)
    dt = float(np.median(dts))
    info = {"fs": 1.0 / dt, "max_gap_ms": float(dts.max() * 1000), "resampled": False,
            "gap_samples": int(np.sum(dts > 3 * dt))}
    if np.std(dts) > 0.02 * dt or info["gap_samples"]:
        grid = np.arange(t[0], t[-1], dt)
        x = np.interp(grid, t, x)
        t = grid
        info["resampled"] = True
    return t, x, info


def pick_axis(data: np.ndarray, requested: str = "auto") -> int:
    """Column of the accelerometer axis to analyse. 'auto' = the axis with the most vibration
    energy (the hub's mounting orientation relative to the printer's Y is not assumed)."""
    if requested.lower() in ("x", "y", "z"):
        return {"x": 1, "y": 2, "z": 3}[requested.lower()]
    energy = [float(np.var(scipy.signal.detrend(data[:, c]))) for c in (1, 2, 3)]
    return 1 + int(np.argmax(energy))


def estimate_zeta(freqs: np.ndarray, psd: np.ndarray, f_peak: float) -> Tuple[float, str]:
    """Damping ratio from the half-power bandwidth of the main peak: zeta = (f2 - f1) / (2 f_peak)."""
    i = int(np.argmin(np.abs(freqs - f_peak)))
    half = psd[i] / 2.0
    lo = i
    while lo > 0 and psd[lo] > half:
        lo -= 1
    hi = i
    while hi < len(psd) - 1 and psd[hi] > half:
        hi += 1
    if lo == 0 or hi == len(psd) - 1 or psd[lo] > half or psd[hi] > half:
        return DEFAULT_ZETA, "default (peak too broad or at the band edge)"

    def cross(a, b):                                     # linear interpolation of the half-power crossing
        if psd[a] == psd[b]:
            return freqs[a]
        return freqs[a] + (half - psd[a]) * (freqs[b] - freqs[a]) / (psd[b] - psd[a])

    f1, f2 = cross(lo, lo + 1), cross(hi - 1, hi)
    z = (f2 - f1) / (2.0 * f_peak)
    if not 0.02 <= z <= 0.30:
        return DEFAULT_ZETA, f"default (measured {z:.3f} is outside 0.02-0.30)"
    return float(z), "half-power bandwidth"


def remaining_vibration(A, t, freqs, psd, zetas=TEST_ZETAS) -> float:
    """Fraction of the (above-threshold) vibration that survives the shaper, worst case over
    `zetas`. Vibration below 1/20 of the peak is ignored: a shaper cannot reduce it further."""
    thr = psd.max() / 20.0
    total = np.maximum(psd - thr, 0.0).sum()
    if total <= 0:
        return 0.0
    worst = 0.0
    for z in zetas:
        v = InputShaperModel.transfer_function(A, t, freqs, z)
        worst = max(worst, float(np.maximum(v * psd - thr, 0.0).sum() / total))
    return worst


def fit_shaper(name: str, freqs: np.ndarray, psd: np.ndarray, zeta: float = DEFAULT_ZETA,
               f_max: Optional[float] = None, step: float = 0.5) -> Dict:
    """Best shaper frequency for one family: lowest smoothing * (vibr^1.5 + 0.2 vibr + 0.01)."""
    f_max = min(f_max or BAND_HZ[1], BAND_HZ[1])
    best = None
    for f in np.arange(MIN_SHAPER_FREQ[name], f_max + 1e-9, step):
        A, t = InputShaperModel.get_shaper_params(name, f, zeta)
        v = remaining_vibration(A, t, freqs, psd)
        sm = InputShaperModel.smoothing(A, t)
        score = sm * (v ** 1.5 + 0.2 * v + 0.01)
        if best is None or score < best["score"] - 1e-12:
            best = {"type": name, "freq": float(f), "vibration_fraction": v, "smoothing_mm": sm, "score": score}
    A, t = InputShaperModel.get_shaper_params(name, best["freq"], zeta)
    best["max_accel"] = InputShaperModel.max_accel(A, t)
    best["residual_pct"] = best["vibration_fraction"] * 100.0
    best["vibration_reduction_pct"] = 100.0 - best["residual_pct"]
    best["H"] = InputShaperModel.transfer_function(A, t, freqs, zeta)
    thr = psd.max() / 20.0
    best["filtered_psd"] = np.maximum(best["H"] * psd, 0.0)
    best["A"], best["T"] = A, t
    return best


def analyze_resonances(data, axis_col=2, max_freq=BAND_HZ[1]):
    """PSD, resonance peak, damping and the best setting for each shaper family.
    axis_col: 1 = X, 2 = Y, 3 = Z of the accelerometer."""
    t = np.asarray(data[:, 0], dtype=float)
    t = t - t[0]
    t, accel, info = resample_uniform(t, np.asarray(data[:, axis_col], dtype=float))
    fs = info["fs"]
    print(f"[DSP] fs = {fs:.1f} Hz, N = {len(t)}, T = {t[-1]:.2f} s"
          + (f", resampled onto a uniform grid (max gap {info['max_gap_ms']:.1f} ms)" if info["resampled"] else ""))

    detrended = scipy.signal.detrend(accel)
    nperseg = max(64, min(len(detrended), int(fs * 0.5)))
    freqs, psd = scipy.signal.welch(detrended, fs=fs, window="hann", nperseg=nperseg, noverlap=nperseg // 2)
    mask = (freqs >= BAND_HZ[0]) & (freqs <= max_freq)
    freqs, psd = freqs[mask], psd[mask]
    if len(freqs) < 8 or not np.any(psd > 0):
        raise ValueError("not enough spectral content in 5-%g Hz: capture too short or sensor not excited" % max_freq)

    peak = int(np.argmax(psd))
    f_peak, p_peak = float(freqs[peak]), float(psd[peak])
    zeta, zeta_src = estimate_zeta(freqs, psd, f_peak)
    print(f"[DSP] resonance peak f0 = {f_peak:.2f} Hz, zeta = {zeta:.3f} ({zeta_src})")

    shapers = {n: fit_shaper(n, freqs, psd, zeta, f_max=max_freq) for n in SHAPER_TYPES}
    for s in shapers.values():
        s["freq_vs_peak_pct"] = (s["freq"] / f_peak - 1.0) * 100.0
    # Recommendation: best score; ties (within 20 %) resolved by the higher allowed acceleration
    ranked = sorted(shapers.values(), key=lambda s: s["score"])
    best = ranked[0]
    for s in ranked[1:]:
        if s["score"] <= best["score"] * 1.2 and s["max_accel"] > best["max_accel"]:
            best = s
    return {"time": t, "accel_raw": accel, "accel_detrended": detrended, "fs": fs, "freqs": freqs, "psd": psd,
            "primary_freq": f_peak, "primary_psd": p_peak, "zeta": zeta, "zeta_source": zeta_src,
            "sampling": info, "shapers": shapers, "best": best}


# ── output ───────────────────────────────────────────────────────────────────────────
def snippet(analysis, axis_name="Y") -> str:
    best, ax = analysis["best"], axis_name.lower()
    return (f"# Indus3D input shaper calibration ({axis_name} axis) {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# resonance {analysis['primary_freq']:.2f} Hz, zeta {analysis['zeta']:.3f} ({analysis['zeta_source']})\n"
            f"[input_shaper]\nshaper_type_{ax}: {best['type'].lower()}\nshaper_freq_{ax}: {best['freq']:.1f}\n"
            f"# max_accel at the smoothing limit: {best['max_accel']} mm/s^2 (set it in [printer] if you want it)\n")


_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_AUTOSAVE = "#*# <---- SAVE_CONFIG ---->"


def update_printer_cfg_text(text: str, axis: str, shaper_type: str, freq: float) -> Tuple[str, List[str]]:
    """New printer.cfg text with shaper_type_<axis>/shaper_freq_<axis> set in [input_shaper], and
    warnings. Other keys (the other axis, damping ratios, ...) are untouched."""
    ax = axis.lower()
    warnings: List[str] = []
    head, sep, auto = text.partition(_AUTOSAVE)
    if sep and re.search(rf"^#\*#\s*shaper_(type|freq)_{ax}\s*=", auto, re.M):
        warnings.append(f"an auto-saved shaper_*_{ax} exists below '{_AUTOSAVE.strip()}' (from SHAPER_CALIBRATE + "
                        "SAVE_CONFIG). Klipper gives it precedence over this edit: delete those #*# lines or this "
                        "change has no effect.")
    lines = head.splitlines()
    new_lines = {f"shaper_type_{ax}": f"shaper_type_{ax}: {shaper_type.lower()}",
                 f"shaper_freq_{ax}": f"shaper_freq_{ax}: {freq:.1f}"}
    sec_start = next((i for i, l in enumerate(lines) if (m := _SECTION.match(l)) and m.group(1).strip() == "input_shaper"), None)
    if sec_start is None:
        block = ["[input_shaper]", *new_lines.values(), ""]
        lines = lines + ([""] if lines and lines[-1].strip() else []) + block
    else:
        end = next((i for i in range(sec_start + 1, len(lines)) if _SECTION.match(lines[i])), len(lines))
        done = set()
        for i in range(sec_start + 1, end):
            m = re.match(r"^\s*([A-Za-z_]+)\s*[:=]", lines[i])
            if m and m.group(1) in new_lines:
                lines[i] = new_lines[m.group(1)]
                done.add(m.group(1))
        insert_at = end
        while insert_at > sec_start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1                                   # keep trailing blank lines after the section
        for k in new_lines:
            if k not in done:
                lines.insert(insert_at, new_lines[k])
                insert_at += 1
    out = "\n".join(lines).rstrip("\n") + "\n"
    return (out + ("\n" if auto else "") + (sep + auto if sep else "")) if sep else out, warnings


def apply_to_printer_cfg(path: str, axis: str, shaper_type: str, freq: float) -> List[str]:
    """Write the recommendation into printer.cfg (timestamped backup first). Returns warnings."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new, warnings = update_printer_cfg_text(text, axis, shaper_type, freq)
    backup = f"{path}.indus3d_bak_{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    print(f"[CONFIG] updated [input_shaper] in {path} (backup: {backup})")
    return warnings


def generate_report_and_plots(analysis, output_dir, axis_name="Y"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(output_dir, exist_ok=True)
    best = analysis["best"]
    print("\n" + "=" * 78)
    print(f" INPUT SHAPER CALIBRATION REPORT (BED / {axis_name}-AXIS)")
    print("=" * 78)
    print(f" Resonance peak: {analysis['primary_freq']:.2f} Hz   damping ratio: {analysis['zeta']:.3f} ({analysis['zeta_source']})")
    print(f" Sampling:       {analysis['fs']:.0f} Hz" + ("  (resampled)" if analysis["sampling"]["resampled"] else ""))
    print("-" * 78)
    print(f"{'Shaper':<10} | {'Freq (Hz)':<9} | {'Vib. removed':<12} | {'Smoothing':<10} | {'Max accel':<10}")
    print("-" * 78)
    for st, s in analysis["shapers"].items():
        tag = "  <- recommended" if st == best["type"] else ""
        print(f"{st:<10} | {s['freq']:<9.1f} | {s['vibration_reduction_pct']:<11.1f}% | "
              f"{s['smoothing_mm']:<7.3f} mm | {s['max_accel']:<6d}{tag}")
    print("=" * 78)
    ax = axis_name.lower()
    print(f"  shaper_type_{ax}: {best['type'].lower()}\n  shaper_freq_{ax}: {best['freq']:.1f}\n"
          f"  max_accel at the {TARGET_SMOOTHING_MM} mm smoothing limit: {best['max_accel']} mm/s^2")
    print("=" * 78 + "\n")

    cfg_path = os.path.join(output_dir, f"bed_input_shaper_{ax}.cfg")
    with open(cfg_path, "w") as f:
        f.write(snippet(analysis, axis_name))
    print(f"[CONFIG] wrote {cfg_path}")

    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), dpi=150)
    fig.suptitle(f"Indus3D ESP8266 Bed Resonance & Input Shaper Analysis ({axis_name}-axis)", fontsize=14, fontweight="bold")
    a1 = axes[0, 0]
    n = min(len(analysis["time"]), int(analysis["fs"] * 1.5))
    a1.plot(analysis["time"][:n], analysis["accel_detrended"][:n], color="#1f77b4", lw=1.0)
    a1.set(title="Time-domain bed vibration (first 1.5 s)", xlabel="Time (s)", ylabel="Acceleration (g)")
    a2 = axes[0, 1]
    a2.plot(analysis["freqs"], analysis["psd"], color="#d62728", lw=1.5, label="PSD")
    a2.axvline(analysis["primary_freq"], color="black", ls=":", lw=1.5,
               label=f"f0 = {analysis['primary_freq']:.1f} Hz, zeta = {analysis['zeta']:.2f}")
    a2.set(title="Power spectral density", xlabel="Frequency (Hz)", ylabel="PSD (g^2/Hz)", yscale="log")
    a2.legend(loc="upper right")
    a3 = axes[1, 0]
    colors = ["#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#17becf"]
    for i, (st, s) in enumerate(analysis["shapers"].items()):
        a3.plot(analysis["freqs"], s["H"], lw=2.2 if st == best["type"] else 1.1, color=colors[i % 6],
                label=f"{st} @ {s['freq']:.1f} Hz" + (" (best)" if st == best["type"] else ""))
    a3.axvline(analysis["primary_freq"], color="black", ls=":", alpha=0.7)
    a3.set(title="Residual vibration V(f) of each shaper", xlabel="Frequency (Hz)", ylabel="V(f)", ylim=(-0.05, 1.1))
    a3.legend(loc="lower right", ncol=2, fontsize=8)
    a4 = axes[1, 1]
    a4.plot(analysis["freqs"], analysis["psd"], color="#d62728", lw=1.0, alpha=0.4, label="unfiltered")
    a4.plot(analysis["freqs"], best["filtered_psd"], color="#2ca02c", lw=1.8,
            label=f"{best['type']} ({best['vibration_reduction_pct']:.0f}% removed)")
    a4.set(title=f"Spectrum after the {best['type']} shaper", xlabel="Frequency (Hz)", ylabel="PSD (g^2/Hz)", yscale="log")
    a4.legend(loc="upper right")
    plt.tight_layout()
    plot_path = os.path.join(output_dir, f"shaper_calibration_bed_{ax}.png")
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"[PLOT] {plot_path}")


def run_analysis(csv_path: str, axis: str = "Y", outdir: str = "output", apply_to: Optional[str] = None,
                 accel_axis: str = "auto") -> int:
    data = load_csv_data(csv_path)
    col = pick_axis(data, accel_axis)
    print(f"[AXIS] analysing accelerometer axis {'XYZ'[col - 1]} "
          f"({'chosen automatically: highest vibration energy' if accel_axis == 'auto' else 'as requested'})")
    analysis = analyze_resonances(data, axis_col=col)
    generate_report_and_plots(analysis, outdir, axis_name=axis.upper())
    if apply_to:
        best = analysis["best"]
        for w in apply_to_printer_cfg(apply_to, axis, best["type"], best["freq"]):
            print(f"[WARNING] {w}")
        print("Restart Klipper (RESTART) to load the new [input_shaper].")
    return 0


# ── capture sources ──────────────────────────────────────────────────────────────────
def capture_via_daemon(url: str, duration: int, rate: int, baud: Optional[int], outdir: str) -> Optional[str]:
    """Ask the hub daemon (the only owner of the serial port) for a capture; returns the CSV path."""
    body = {"duration": duration, "rate": rate}
    if baud:
        body["baud"] = baud
    req = urllib.request.Request(url.rstrip("/") + "/shaper/capture", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Indus3D-Action": "1"})
    print(f"[DAEMON] requesting a {duration} s capture at {rate} Hz ...")
    try:
        with urllib.request.urlopen(req, timeout=duration + 40) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        res = json.loads(e.read() or b"{}")
    except OSError as e:
        print(f"[ERROR] cannot reach the hub daemon at {url}: {e}")
        return None
    if not res.get("ok"):
        print(f"[ERROR] capture failed: {res.get('error')}")
        return None
    print(f"[DAEMON] {res['samples']} samples @ {res['rate_hz']} Hz, loss {res['loss_pct']} % ({res['quality']})")
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, "resonances_bed_capture.csv")
    shutil.copy(res["csv"], dst)
    return dst


def capture_tcp_stream(ip, port=8266, duration_s=5, rate_hz=1600):
    """WiFi mode only (ENABLE_WIFI in the firmware): collect the binary stream from the hub's TCP server."""
    import socket
    print(f"[TCP] connecting to {ip}:{port} ...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(duration_s + 4.0)
    try:
        sock.connect((ip, port))
    except OSError as e:
        print(f"[ERROR] cannot connect: {e}")
        return None
    raw, start = bytearray(), time.time()
    while time.time() - start < duration_s + 1.0:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) >= duration_s * rate_hz * PACKET_SIZE:
            break
    sock.close()
    return unpack_binary_frames(raw)


def main():
    ap = argparse.ArgumentParser(description="Indus3D ESP8266 input shaper resonance analyzer")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--csv", help="analyse an existing capture (Klipper CSV: time,accel_x,accel_y,accel_z)")
    src.add_argument("--ip", help="WiFi mode: ESP8266 address for the TCP stream")
    src.add_argument("--serial", help=argparse.SUPPRESS)
    ap.add_argument("--daemon-url", default=os.environ.get("INDUS3D_BED_HUB_URL", "http://127.0.0.1:7127"),
                    help="hub daemon API used for captures (default: %(default)s)")
    ap.add_argument("--port", type=int, default=8266, help="TCP stream port (WiFi mode)")
    ap.add_argument("--duration", type=int, default=7)
    ap.add_argument("--rate", type=int, default=1600, choices=[200, 400, 800, 1600, 3200])
    ap.add_argument("--baud", type=int, default=None, help="serial baud for the capture (default: smallest that carries --rate)")
    ap.add_argument("--axis", default="Y", choices=["X", "Y", "Z"], help="printer axis being tuned (names the config keys)")
    ap.add_argument("--accel-axis", default="auto", choices=["auto", "x", "y", "z"],
                    help="which accelerometer axis to analyse (default: the one with the most vibration)")
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--apply-to", metavar="PRINTER_CFG", help="update [input_shaper] in this printer.cfg (backup first)")
    args = ap.parse_args()

    if args.serial:
        print("[ERROR] --serial is no longer supported: the hub daemon owns the serial port and two processes "
              "cannot share it. Capture through the daemon (default) or analyse a CSV with --csv.")
        return 1
    csv_path = args.csv
    if args.ip:
        data = capture_tcp_stream(args.ip, args.port, args.duration, args.rate)
        if data is None:
            return 1
        os.makedirs(args.outdir, exist_ok=True)
        csv_path = os.path.join(args.outdir, "resonances_bed_capture.csv")
        save_klipper_csv(data, csv_path)
    elif not csv_path:
        csv_path = capture_via_daemon(args.daemon_url, args.duration, args.rate, args.baud, args.outdir)
        if not csv_path:
            return 1
    return run_analysis(csv_path, args.axis, args.outdir, args.apply_to, args.accel_axis)


if __name__ == "__main__":
    sys.exit(main())
