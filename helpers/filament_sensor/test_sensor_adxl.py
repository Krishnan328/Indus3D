#!/usr/bin/env python3
"""
Test script for Smart Filament Sensor with Bed ADXL345 Telemetry over USB Serial.
Supports BMG motion tracking, diameter sensing, and real-time bed accelerometer / jerk display.

Usage:
    python3 test_sensor_adxl.py [SERIAL_PORT]

Commands while running:
    Press 'd' + Enter: Toggle live ASCII debug stream from Pico
    Press 'z' + Enter: Zero / reset motion distance counter
    Press 'c' + Enter: Tare / calibrate current diameter to nominal 1.750 mm
    Press 'e' + Enter: Tare empty bearings to 0.000 mm
    Press 'w' + Enter: Save calibration to Flash
    Press 'b' + Enter: Jump to Katapult / ROM bootloader
    Press Ctrl+C:      Exit
"""

import sys
import time
import math
import struct
import glob
import select
import serial
import shutil

MAGNET_STATES = {
    0: "UNKNOWN",
    1: "NOT_DETECTED",
    2: "TOO_WEAK",
    3: "TOO_STRONG",
    4: "DETECTED (OK)"
}

FAULT_MASKS = {
    0x01: "STALL/SLIP DETECTED",
    0x02: "REVERSING",
    0x04: "DIA OUT-OF-SPEC",
    0x08: "FILAMENT RUNOUT",
    0x10: "BED CRASH / SHOCK DETECTED"
}

def decode_faults(flags):
    active = [name for mask, name in FAULT_MASKS.items() if flags & mask]
    return ", ".join(active) if active else "NORMAL"

def find_serial_port():
    ports = glob.glob('/dev/tty.usbmodem*') + glob.glob('/dev/ttyACM*')
    if ports:
        return ports[0]
    return None

def main():
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        port = find_serial_port()
        if not port:
            print("No Pico USB serial device found! Specify the port manually:")
            print("Usage: python3 test_sensor_adxl.py /dev/tty...")
            sys.exit(1)

    print(f"Connecting to {port} at 115200 baud...")
    try:
        ser = serial.Serial(port, 115200, timeout=0.15)
    except Exception as e:
        print(f"Failed to open port: {e}")
        sys.exit(1)

    time.sleep(0.5)
    ser.reset_input_buffer()

    print("\n" + "=" * 90)
    print("  SMART FILAMENT SENSOR + BED ADXL345 ACCELEROMETER TELEMETRY DASHBOARD")
    print("=" * 90)
    print("  Controls:")
    print("    'd' -> Toggle raw ASCII stream from Pico (includes live [BED] X/Y/Z mg & jerk)")
    print("    'z' -> Zero motion distance counter")
    print("    'e' -> Tare empty bearings (0.000 mm)")
    print("    'c' -> Tare filament diameter span")
    print("    'w' -> Save calibrations permanently to RP2040 Flash")
    print("    'b' -> Jump to Bootloader")
    print("    Ctrl+C -> Exit")
    print("=" * 90 + "\n")

    buffer = bytearray()

    try:
        while True:
            # Check for user keyboard input (non-blocking)
            if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                cmd = sys.stdin.readline().strip().lower()
                if cmd == 'e':
                    ser.write(bytearray([0xF5, 0x22]))
                    ser.write(b'e')
                    print("\n[CMD] Tared empty bearings reference to 0.000 mm.")
                elif cmd == 'c':
                    ser.write(bytearray([0xF5, 0x23, 0xD6, 0x06])) # 1750 um default
                    ser.write(b'c\n')
                    print("\n[CMD] Calibrated span to nominal 1.750 mm.")
                elif cmd == 'w':
                    ser.write(bytearray([0xF5, 0x24]))
                    ser.write(b'w')
                    print("\n[CMD] Saved calibration to Flash.")
                elif cmd == 'z':
                    ser.write(b'z')
                    print("\n[CMD] Zeroed motion distance counter.")
                elif cmd == 'd':
                    ser.write(b'd')
                    print("\n[CMD] Toggled live ASCII stream.")
                elif cmd == 'b':
                    ser.write(b'b')
                    print("\n[CMD] Jumping to bootloader.")
                    break

            # Send binary query packet: 0xF5, 0x10
            ser.write(bytearray([0xF5, 0x10]))

            # Read any available data
            chunk = ser.read(64)
            if chunk:
                buffer.extend(chunk)

            # Check if buffer has an ASCII text line (e.g. from debug stream)
            if b'\n' in buffer and not (buffer.startswith(b'\x05\xff\x10')):
                line_end = buffer.index(b'\n')
                line = buffer[:line_end].decode('utf-8', errors='ignore').strip()
                buffer = buffer[line_end + 1:]
                if line:
                    print(f"\r{line}")
                continue

            # Check for new 41-byte binary response (3 header + 38 payload)
            while len(buffer) >= 41:
                idx = buffer.find(b'\x05\xff\x10')
                if idx == -1:
                    buffer = buffer[-2:]
                    break
                if idx > 0:
                    buffer = buffer[idx:]

                if len(buffer) < 41:
                    break

                payload = buffer[3:41]
                buffer = buffer[41:]

                (motion_mag, dia_mag, present, fault_flags,
                 motion_turns, motion_ang, total_counts, total_um,
                 velocity_um_s, dia_raw_ang, dia_filtered_um, dia_variance_um,
                 bed_x_mg, bed_y_mg, bed_z_mg, bed_jerk) = struct.unpack('<BBBBllllhlhhhhhh', payload)

                motion_str = MAGNET_STATES.get(motion_mag, f"MAG:{motion_mag}")
                dia_str = MAGNET_STATES.get(dia_mag, f"MAG:{dia_mag}")
                sw_str = "PRESENT" if present else "RUNOUT"
                fault_str = decode_faults(fault_flags)

                pos_mm = total_um / 1000.0
                speed_mm_s = velocity_um_s / 1000.0
                dia_mm = dia_filtered_um / 1000.0
                ripple_mm = dia_variance_um / 1000.0

                cols, _ = shutil.get_terminal_size((120, 24))
                line = (f"[MOT] Pos: {pos_mm:+7.2f}mm ({speed_mm_s:+5.1f}mm/s) | "
                        f"[DIA] {dia_mm:5.3f}mm (Rip:{ripple_mm:5.3f}) | "
                        f"[BED] X:{bed_x_mg:+5d} Y:{bed_y_mg:+5d} Z:{bed_z_mg:+5d} mg (Jerk:{bed_jerk:4d}) | "
                        f"Status: {fault_str}")
                sys.stdout.write("\r" + line[:cols].ljust(cols))
                sys.stdout.flush()

            time.sleep(0.04) # ~25 Hz update

    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        ser.close()

if __name__ == '__main__':
    main()
