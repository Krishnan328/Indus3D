#!/usr/bin/env bash
""":"
# Python wrapper for universal calibration
which python3 >/dev/null 2>&1 && exec python3 "$0" "$@"
exec python "$0" "$@"
"""
import sys
import time
import json
import urllib.request
import urllib.error

API_URL = "http://127.0.0.1:7126"

def get_daemon_status():
    try:
        with urllib.request.urlopen(f"{API_URL}/status", timeout=1.0) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def tare_empty_daemon():
    try:
        with urllib.request.urlopen(f"{API_URL}/tare_empty", timeout=2.0) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Error calling tare_empty: {e}")
        return False

def calibrate_span_daemon(target_mm: float):
    try:
        url = f"{API_URL}/calibrate_span?target={target_mm:.3f}"
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Error calling calibrate_span: {e}")
        return False

def main():
    print("=" * 70)
    print("  INDUS3D SMART FILAMENT SENSOR - TWO-POINT CALIBRATION WIZARD")
    print("=" * 70)

    status = get_daemon_status()
    if not status or not status.get("connected"):
        print("\n[!] The Indus3D daemon does not appear to be running or connected.")
        print("    Please ensure 'python3 indus3d_sensor_daemon.py' is running,")
        print("    or open http://localhost:7126 in your web browser.")
        sys.exit(1)

    print(f"\n[OK] Connected to sensor daemon on {status.get('port')}")
    print(f"     Current Raw Angle: {status.get('raw_dia_angle')}")
    print(f"     Current Reading:   {status.get('diameter_mm', 0):.3f} mm")
    print(f"     Filament Switch:   {'PRESENT' if status.get('filament_present') else 'RUNOUT / EMPTY'}")

    print("\n" + "-" * 70)
    print("STEP 1: EMPTY BEARINGS TARE (0.000 mm)")
    print("-" * 70)
    print("1. Ensure there is NO filament inside the sensor.")
    print("2. Ensure the two 10mm bearings are resting naturally against each other.")
    input("\nPress [Enter] when the sensor is completely empty to tare...")

    print("Sending Tare Empty command to Pico Flash...")
    if tare_empty_daemon():
        time.sleep(0.5)
        st = get_daemon_status()
        print(f"-> SUCCESS: Empty baseline tared to raw angle {st.get('raw_dia_angle')}!")
        print(f"   Current Diameter: {st.get('diameter_mm'):.3f} mm (Switch: {'PRESENT' if st.get('filament_present') else 'EMPTY'})")
    else:
        print("-> FAILED to tare empty bearings. Check sensor connection.")
        sys.exit(1)

    print("\n" + "-" * 70)
    print("STEP 2: FILAMENT SPAN CALIBRATION")
    print("-" * 70)
    print("1. Insert a piece of standard filament between the bearings.")
    print("2. (Optional) Measure your filament diameter with calipers.")
    val_str = input("\nEnter measured diameter in mm [default: 1.75]: ").strip()
    target_mm = 1.75
    if val_str:
        try:
            target_mm = float(val_str)
        except ValueError:
            print("Invalid number entered; defaulting to 1.75 mm.")
            target_mm = 1.75

    print(f"Calibrating span to {target_mm:.3f} mm...")
    if calibrate_span_daemon(target_mm):
        time.sleep(0.5)
        st = get_daemon_status()
        print(f"-> SUCCESS: Calibrated and saved to Flash!")
        print(f"   Diameter Reading: {st.get('diameter_mm'):.3f} mm (Switch: {'PRESENT' if st.get('filament_present') else 'EMPTY'})")
    else:
        print("-> FAILED to calibrate span.")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("VERIFICATION")
    print("=" * 70)
    print("Pull the filament out and push it back in while watching below:")
    print("Press Ctrl+C to exit when satisfied.\n")

    try:
        while True:
            st = get_daemon_status()
            if st:
                dia = st.get('diameter_mm', 0.0)
                pres = st.get('filament_present', False)
                raw = st.get('raw_dia_angle', 0)
                state_str = "\033[92mFILAMENT OK\033[0m" if pres else "\033[91mRUNOUT (EMPTY)\033[0m"
                print(f"\r  Dia: {dia:5.3f} mm | Raw Angle: {raw:4d} | State: {state_str}    ", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nCalibration wizard finished. Flash settings are permanent across power cycles.")

if __name__ == "__main__":
    main()
