#!/usr/bin/env python3
"""
Indus3D ESP8266 Input Shaper Resonance Analyzer
================================================
Processes high-frequency accelerometer stream from ESP8266 Multi-Sensor Hub,
computes Power Spectral Density (PSD), calculates resonance peaks, models
Klipper input shaper transfer functions (ZV, MZV, ZVD, EI, 2HUMP_EI, 3HUMP_EI),
recommends optimal shaper configuration, and generates publication-grade plots.

Author: Krishnan H (Indus3D Project)
"""

import sys
import os
import time
import socket
import struct
import argparse
import numpy as np
import scipy.signal
import matplotlib
matplotlib.use('Agg') # Headless plotting
import matplotlib.pyplot as plt

# Binary packet format from ESP8266 ShaperStreamer (15 bytes)
# [0xAA, 0x55] [uint16 seq] [uint32 time_us] [int16 x] [int16 y] [int16 z] [uint8 crc]
PACKET_FORMAT = "<BBHIhhhB"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
MAGIC_0 = 0xAA
MAGIC_1 = 0x55

# Full-res ADXL345 scale: 3.90625 mg/LSB -> 0.00390625 g/LSB
SCALE_G_PER_LSB = 0.00390625
GRAVITY_MM_S2 = 9806.65 # 1g in mm/s^2


class InputShaperModel:
    """
    Mathematical models for standard Klipper Input Shaper filters.
    Calculates impulse amplitudes A_i and time delays t_i, then evaluates
    the shaper transfer function H(f) and residual vibration spectrum.
    """

    @staticmethod
    def get_shaper_params(shaper_type, f_shaper, damping_ratio=0.1):
        """
        Returns (amplitudes, times) for the given shaper type.
        """
        st = shaper_type.upper()
        T_d = 1.0 / (f_shaper * np.sqrt(1.0 - damping_ratio**2))
        K = np.exp(-damping_ratio * np.pi / np.sqrt(1.0 - damping_ratio**2))

        if st == "ZV":
            A = np.array([1.0, K])
            t = np.array([0.0, 0.5 * T_d])
        elif st == "ZVD":
            A = np.array([1.0, 2.0 * K, K**2])
            t = np.array([0.0, 0.5 * T_d, T_d])
        elif st == "MZV":
            K_m = np.exp(-0.75 * damping_ratio * np.pi / np.sqrt(1.0 - damping_ratio**2))
            A = np.array([1.0, 2.0 * K_m * np.cos(np.pi / 4.0), K_m**2])
            t = np.array([0.0, 0.375 * T_d, 0.75 * T_d])
        elif st == "EI":
            v_tol = 0.05
            A = np.array([1.0, 2.0 * K, K**2]) # base 3-impulse EI approximation
            t = np.array([0.0, 0.5 * T_d, T_d])
        elif st == "2HUMP_EI":
            A = np.array([1.0, 3.0 * K, 3.0 * K**2, K**3])
            t = np.array([0.0, 0.5 * T_d, T_d, 1.5 * T_d])
        elif st == "3HUMP_EI":
            A = np.array([1.0, 4.0 * K, 6.0 * K**2, 4.0 * K**3, K**4])
            t = np.array([0.0, 0.5 * T_d, T_d, 1.5 * T_d, 2.0 * T_d])
        else:
            raise ValueError(f"Unknown shaper type: {shaper_type}")

        A = A / np.sum(A) # Normalize amplitudes to sum to 1.0
        return A, t

    @staticmethod
    def transfer_function(A, t, freqs, damping_ratio=0.1):
        """
        Evaluates the exact residual vibration ratio V(f) of an underdamped oscillator:
        V(omega) = e^(-zeta * omega * t_N) * sqrt(C(omega)^2 + S(omega)^2)
        where:
          C(omega) = sum_i A_i * e^(zeta * omega * t_i) * cos(omega_d * t_i)
          S(omega) = sum_i A_i * e^(zeta * omega * t_i) * sin(omega_d * t_i)
          omega = 2 * pi * f, omega_d = omega * sqrt(1 - zeta^2)
        """
        omega = 2.0 * np.pi * freqs
        omega_d = omega * np.sqrt(1.0 - damping_ratio**2)
        t_N = t[-1]

        C = np.zeros_like(freqs, dtype=float)
        S = np.zeros_like(freqs, dtype=float)

        for a_i, t_i in zip(A, t):
            exp_factor = a_i * np.exp(damping_ratio * omega * t_i)
            C += exp_factor * np.cos(omega_d * t_i)
            S += exp_factor * np.sin(omega_d * t_i)

        V = np.exp(-damping_ratio * omega * t_N) * np.sqrt(C**2 + S**2)
        return V

    @staticmethod
    def shaper_accel_factor(shaper_type):
        """
        Approximate maximum acceleration factor: max_accel <= factor * freq
        Based on Klipper input shaper smoothing guidelines.
        """
        factors = {
            "ZV": 105.0,
            "MZV": 75.0,
            "ZVD": 52.0,
            "EI": 50.0,
            "2HUMP_EI": 35.0,
            "3HUMP_EI": 25.0,
        }
        return factors.get(shaper_type.upper(), 50.0)


def unpack_binary_frames(raw_bytes):
    """
    Decodes raw bytes into accelerometer samples [(t_s, x_g, y_g, z_g), ...].
    """
    samples = []
    offset = 0
    total_len = len(raw_bytes)

    while offset + PACKET_SIZE <= total_len:
        # Check magic bytes 0xAA, 0x55
        if raw_bytes[offset] == MAGIC_0 and raw_bytes[offset + 1] == MAGIC_1:
            pkt = struct.unpack_from(PACKET_FORMAT, raw_bytes, offset)
            m0, m1, seq, time_us, x_raw, y_raw, z_raw, crc = pkt

            # Verify XOR checksum
            chk = 0
            for b in raw_bytes[offset : offset + PACKET_SIZE - 1]:
                chk ^= b
            if chk == crc:
                samples.append((time_us * 1e-6, x_raw * SCALE_G_PER_LSB, y_raw * SCALE_G_PER_LSB, z_raw * SCALE_G_PER_LSB))
            offset += PACKET_SIZE
        else:
            # Resync to next byte
            offset += 1

    print(f"[PARSER] Successfully decoded {len(samples)} valid accelerometer frames.")
    return np.array(samples) if samples else None


def find_serial_port():
    """Auto-detects USB serial device for ESP8266."""
    import glob
    candidates = (
        glob.glob("/dev/cu.usbserial*") + 
        glob.glob("/dev/cu.wchusbserial*") + 
        glob.glob("/dev/cu.SLAB_USBtoUART*") + 
        glob.glob("/dev/ttyUSB*") + 
        glob.glob("/dev/ttyACM*")
    )
    return candidates[0] if candidates else None


def capture_serial_stream(port=None, baud=115200, duration_s=5, rate_hz=1600):
    """
    Connects to ESP8266 via USB Serial, issues START_SHAPER command,
    and captures binary accelerometer frames directly over USB.
    """
    import serial
    if not port or port.lower() == "auto":
        port = find_serial_port()
        if not port:
            print("[ERROR] No USB serial port detected. Please specify --serial <PORT>.")
            return None

    print(f"[SERIAL] Opening {port} at {baud} baud...")
    ser = serial.Serial(port, baud, timeout=1.0)
    time.sleep(1.0)
    ser.reset_input_buffer()

    cmd = f"START_SHAPER {duration_s} {rate_hz}\n"
    print(f"[SERIAL] Sending command: {cmd.strip()}")
    ser.write(cmd.encode('utf-8'))
    ser.flush()

    raw_bytes = bytearray()
    expected_samples = duration_s * rate_hz
    start_time = time.time()

    print(f"[SERIAL] Streaming binary accelerometer frames for {duration_s}s...")
    while (time.time() - start_time) < (duration_s + 2.0):
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            raw_bytes.extend(chunk)
            if len(raw_bytes) >= expected_samples * PACKET_SIZE:
                break

    ser.close()
    print(f"[SERIAL] Stream finished. Received {len(raw_bytes)} raw bytes.")
    return unpack_binary_frames(raw_bytes)


def capture_tcp_stream(ip, port=8266, duration_s=5, rate_hz=1600):
    """
    Connects to ESP8266 TCP server and collects binary accelerometer packets.
    """
    print(f"[TCP] Connecting to ESP8266 at {ip}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(duration_s + 4.0)

    try:
        sock.connect((ip, port))
        print(f"[TCP] Connected! Streaming for {duration_s} seconds @ {rate_hz} Hz...")
    except Exception as e:
        print(f"[ERROR] Could not connect to ESP8266 TCP server: {e}")
        return None

    raw_bytes = bytearray()
    expected_samples = duration_s * rate_hz
    start_time = time.time()

    while (time.time() - start_time) < (duration_s + 1.0):
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw_bytes.extend(chunk)
            if len(raw_bytes) >= expected_samples * PACKET_SIZE:
                break
        except socket.timeout:
            break

    sock.close()
    print(f"[TCP] Stream finished. Received {len(raw_bytes)} bytes.")
    return unpack_binary_frames(raw_bytes)


def load_csv_data(csv_path):
    """
    Loads Klipper-format CSV (time,accel_x,accel_y,accel_z).
    """
    print(f"[CSV] Loading accelerometer data from {csv_path}...")
    data = np.genfromtxt(csv_path, delimiter=',', skip_header=1)
    # Check columns
    if data.shape[1] >= 4:
        return data[:, :4]
    raise ValueError(f"Expected at least 4 columns in CSV, got {data.shape[1]}")


def save_klipper_csv(data, output_path):
    """
    Saves data in official Klipper resonance test CSV format.
    """
    header = "time,accel_x,accel_y,accel_z"
    np.savetxt(output_path, data, delimiter=',', header=header, comments='', fmt="%.6f,%.5f,%.5f,%.5f")
    print(f"[CSV] Saved Klipper-compatible resonance data to: {output_path}")


def analyze_resonances(data, axis_col=2, max_freq=150.0):
    """
    Computes FFT and Welch Power Spectral Density (PSD) for the specified axis.
    axis_col: 1 for X, 2 for Y (bed), 3 for Z.
    """
    t = data[:, 0]
    t = t - t[0] # Zero-base time
    accel = data[:, axis_col]

    # Calculate average sampling rate
    dt = np.median(np.diff(t))
    fs = 1.0 / dt
    print(f"[DSP] Detected sampling rate fs = {fs:.1f} Hz (N = {len(t)} samples, T = {t[-1]:.2f} s)")

    # Detrend to remove gravity / DC offset
    accel_detrended = scipy.signal.detrend(accel)

    # Compute Welch's Power Spectral Density
    nperseg = min(len(accel_detrended), int(fs * 0.5)) # 0.5s segment resolution
    freqs, psd = scipy.signal.welch(accel_detrended, fs=fs, window='hann', nperseg=nperseg, noverlap=nperseg // 2)

    # Limit to frequency band [5.0, max_freq]
    valid_mask = (freqs >= 5.0) & (freqs <= max_freq)
    freqs = freqs[valid_mask]
    psd = psd[valid_mask]

    # Find primary resonance peak
    peak_idx = np.argmax(psd)
    primary_freq = freqs[peak_idx]
    primary_psd = psd[peak_idx]

    print(f"[DSP] Primary resonance peak detected: f_0 = {primary_freq:.2f} Hz (PSD = {primary_psd:.2e})")

    # Evaluate all Klipper shaper types
    shaper_types = ["ZV", "MZV", "ZVD", "EI", "2HUMP_EI", "3HUMP_EI"]
    results = {}
    total_raw_vib = np.sum(psd)

    for st in shaper_types:
        A, t_imp = InputShaperModel.get_shaper_params(st, primary_freq)
        H = InputShaperModel.transfer_function(A, t_imp, freqs)
        filtered_psd = psd * (H**2)
        residual_vib = (np.sum(filtered_psd) / total_raw_vib) * 100.0
        accel_factor = InputShaperModel.shaper_accel_factor(st)
        max_accel = int(np.round(primary_freq * accel_factor))

        results[st] = {
            "type": st,
            "freq": primary_freq,
            "residual_pct": residual_vib,
            "vibration_reduction_pct": 100.0 - residual_vib,
            "max_accel": max_accel,
            "H": H,
            "filtered_psd": filtered_psd
        }

    # Best recommendation logic:
    # Prefer MZV or ZVD if residual vibration is low (< 5%), otherwise EI
    sorted_shapers = sorted(results.values(), key=lambda x: (x["residual_pct"], -x["max_accel"]))
    best_shaper = sorted_shapers[0]

    return {
        "time": t,
        "accel_raw": accel,
        "accel_detrended": accel_detrended,
        "fs": fs,
        "freqs": freqs,
        "psd": psd,
        "primary_freq": primary_freq,
        "primary_psd": primary_psd,
        "shapers": results,
        "best": best_shaper
    }


def generate_report_and_plots(analysis, output_dir, axis_name="Y"):
    """
    Generates comparison summary table and publication-grade Matplotlib visual.
    """
    os.makedirs(output_dir, exist_ok=True)
    best = analysis["best"]

    print("\n" + "=" * 70)
    print(f" INPUT SHAPER CALIBRATION REPORT (BED / {axis_name}-AXIS)")
    print("=" * 70)
    print(f" Primary Bed Resonance Frequency: {analysis['primary_freq']:.2f} Hz")
    print(f" Sampling Frequency:              {analysis['fs']:.1f} Hz")
    print("-" * 70)
    print(f"{'Shaper Type':<12} | {'Freq (Hz)':<10} | {'Vib Reduction':<15} | {'Residual %':<12} | {'Max Accel':<12}")
    print("-" * 70)

    for st, s in analysis["shapers"].items():
        is_best = " (RECOMMENDED)" if st == best["type"] else ""
        print(f"{st:<12} | {s['freq']:<10.1f} | {s['vibration_reduction_pct']:<14.1f}% | {s['residual_pct']:<11.1f}% | {s['max_accel']:<5d} mm/s²{is_best}")

    print("=" * 70)
    print(f"RECOMMENDATION:")
    print(f"  shaper_type_{axis_name.lower()} = {best['type'].lower()}")
    print(f"  shaper_freq_{axis_name.lower()} = {best['freq']:.1f}")
    print(f"  Recommended max_accel <= {best['max_accel']} mm/s²")
    print("=" * 70 + "\n")

    # Save Klipper configuration snippet
    cfg_path = os.path.join(output_dir, f"bed_input_shaper_{axis_name.lower()}.cfg")
    with open(cfg_path, "w") as f:
        f.write("# ========================================================\n")
        f.write(f"# Indus3D Automated Input Shaper Calibration ({axis_name}-Axis)\n")
        f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Primary Resonance: {analysis['primary_freq']:.2f} Hz\n")
        f.write("# ========================================================\n\n")
        f.write("[input_shaper]\n")
        f.write(f"shaper_type_{axis_name.lower()} = {best['type'].lower()}\n")
        f.write(f"shaper_freq_{axis_name.lower()} = {best['freq']:.1f}\n\n")
        f.write("[printer]\n")
        f.write(f"# Suggested safe acceleration limit for {best['type']} shaper:\n")
        f.write(f"max_accel: {best['max_accel']}\n")
    print(f"[CONFIG] Wrote Klipper shaper config to: {cfg_path}")

    # Generate 4-panel publication-grade figure
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), dpi=150)
    fig.suptitle(f"Indus3D ESP8266 Bed Resonance & Input Shaper Analysis ({axis_name}-Axis)", fontsize=14, fontweight='bold')

    # Panel 1: Time domain acceleration
    ax1 = axes[0, 0]
    ax1.plot(analysis["time"][:1500], analysis["accel_detrended"][:1500], color='#1f77b4', lw=1.2, label='Detrended Acceleration (g)')
    ax1.set_title("Time-Domain Bed Vibration Signal", fontsize=11, fontweight='semibold')
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Acceleration (g)")
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend(loc='upper right')

    # Panel 2: Power Spectral Density (PSD)
    ax2 = axes[0, 1]
    ax2.plot(analysis["freqs"], analysis["psd"], color='#d62728', lw=1.5, label='Raw PSD')
    ax2.axvline(analysis["primary_freq"], color='black', linestyle=':', lw=1.5,
                label=f"Peak $f_0$ = {analysis['primary_freq']:.1f} Hz")
    ax2.set_title("Power Spectral Density (Vibration Spectrum)", fontsize=11, fontweight='semibold')
    ax2.set_xlabel("Frequency (Hz)")
    ax2.set_ylabel("PSD ($g^2$/Hz)")
    ax2.set_yscale('log')
    ax2.grid(True, which='both', linestyle='--', alpha=0.6)
    ax2.legend(loc='upper right')

    # Panel 3: Shaper Transfer Functions |H(f)|
    ax3 = axes[1, 0]
    colors = ['#2ca02c', '#ff7f0e', '#9467bd', '#8c564b', '#e377c2', '#17becf']
    for idx, (st, s) in enumerate(analysis["shapers"].items()):
        lw = 2.2 if st == best["type"] else 1.2
        label_text = f"{st} (Best)" if st == best["type"] else st
        ax3.plot(analysis["freqs"], s["H"], lw=lw, color=colors[idx % len(colors)], label=label_text)
    ax3.axvline(analysis["primary_freq"], color='black', linestyle=':', alpha=0.7)
    ax3.set_title("Input Shaper Filter Response $|H(f)|$", fontsize=11, fontweight='semibold')
    ax3.set_xlabel("Frequency (Hz)")
    ax3.set_ylabel("Transmission Ratio")
    ax3.set_ylim(-0.05, 1.1)
    ax3.grid(True, linestyle='--', alpha=0.6)
    ax3.legend(loc='lower right', ncol=2, fontsize=9)

    # Panel 4: Residual Vibration Spectrum
    ax4 = axes[1, 1]
    ax4.plot(analysis["freqs"], analysis["psd"], color='#d62728', lw=1.0, alpha=0.4, label='Unfiltered PSD')
    best_s = analysis["shapers"][best["type"]]
    ax4.plot(analysis["freqs"], best_s["filtered_psd"], color='#2ca02c', lw=1.8,
             label=f"{best['type']} Filtered ({best['vibration_reduction_pct']:.1f}% reduction)")
    ax4.set_title(f"Filtered Vibration Spectrum ({best['type']} Shaper)", fontsize=11, fontweight='semibold')
    ax4.set_xlabel("Frequency (Hz)")
    ax4.set_ylabel("PSD ($g^2$/Hz)")
    ax4.set_yscale('log')
    ax4.grid(True, which='both', linestyle='--', alpha=0.6)
    ax4.legend(loc='upper right')

    plt.tight_layout()
    plot_path = os.path.join(output_dir, f"shaper_calibration_bed_{axis_name.lower()}.png")
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"[PLOT] Generated resonance calibration plot at: {plot_path}")


def main():
    parser = argparse.ArgumentParser(description="Indus3D ESP8266 Input Shaper Resonance Analyzer")
    parser.add_argument("--serial", type=str, default=None, help="Serial device port (e.g. /dev/cu.usbserial-*, /dev/ttyUSB0, or 'auto')")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default: 115200)")
    parser.add_argument("--ip", type=str, default=None, help="ESP8266 IP address for high-speed TCP streaming")
    parser.add_argument("--port", type=int, default=8266, help="ESP8266 high-speed TCP stream port (default: 8266)")
    parser.add_argument("--duration", type=int, default=7, help="Excitation sweep duration in seconds (default: 7)")
    parser.add_argument("--rate", type=int, default=1600, choices=[1600, 3200], help="Sampling rate in Hz (default: 1600)")
    parser.add_argument("--csv", type=str, default=None, help="Path to existing Klipper CSV file for offline analysis")
    parser.add_argument("--axis", type=str, default="Y", choices=["X", "Y", "Z"], help="Axis under test (default: Y bed)")
    parser.add_argument("--outdir", type=str, default="output", help="Directory for output graphs and config snippets")
    args = parser.parse_args()

    axis_map = {"X": 1, "Y": 2, "Z": 3}
    axis_col = axis_map[args.axis.upper()]

    if args.csv:
        data = load_csv_data(args.csv)
    elif args.serial:
        data = capture_serial_stream(args.serial, args.baud, args.duration, args.rate)
        if data is None:
            sys.exit(1)
        os.makedirs(args.outdir, exist_ok=True)
        raw_csv_path = os.path.join(args.outdir, f"resonances_bed_{args.axis.lower()}.csv")
        save_klipper_csv(data, raw_csv_path)
    elif args.ip:
        data = capture_tcp_stream(args.ip, args.port, args.duration, args.rate)
        if data is None:
            sys.exit(1)
        os.makedirs(args.outdir, exist_ok=True)
        raw_csv_path = os.path.join(args.outdir, f"resonances_bed_{args.axis.lower()}.csv")
        save_klipper_csv(data, raw_csv_path)
    else:
        # Check if USB serial device is available automatically
        auto_port = find_serial_port()
        if auto_port:
            print(f"[AUTO] Detected USB serial port: {auto_port}. Starting serial capture...")
            data = capture_serial_stream(auto_port, args.baud, args.duration, args.rate)
            if data is None:
                sys.exit(1)
            os.makedirs(args.outdir, exist_ok=True)
            raw_csv_path = os.path.join(args.outdir, f"resonances_bed_{args.axis.lower()}.csv")
            save_klipper_csv(data, raw_csv_path)
        else:
            print("[ERROR] No input specified and no USB serial device auto-detected.")
            print("Please specify --serial <PORT>, --ip <ESP_IP>, or --csv <PATH>.")
            sys.exit(1)

    analysis = analyze_resonances(data, axis_col=axis_col)
    generate_report_and_plots(analysis, args.outdir, axis_name=args.axis.upper())


if __name__ == "__main__":
    main()
