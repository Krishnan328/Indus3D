#!/usr/bin/env python3
"""
Test script for Smart Filament Sensor over USB Serial.
Supports high-resolution BMG motion tracking, calibrated diameter measurement,
and stall/slip fault detection.

Usage:
    python3 test_sensor.py [SERIAL_PORT]

Commands while running:
    Press 'z' + Enter: Zero / reset motion distance counter
    Press 'c' + Enter: Tare / calibrate current diameter to nominal 1.750 mm
    Press 'd' + Enter: Toggle live ASCII debug stream from Pico
    Press 'b' + Enter: Jump to Katapult bootloader
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
    0x08: "FILAMENT RUNOUT"
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
            print("Usage: python3 test_sensor.py /dev/tty...")
            sys.exit(1)

    print(f"Connecting to {port} at 115200 baud...")
    try:
        ser = serial.Serial(port, 115200, timeout=0.15)
    except Exception as e:
        print(f"Failed to open port: {e}")
        sys.exit(1)

    time.sleep(0.5)
    ser.reset_input_buffer()

    print("\n" + "=" * 80)
    print("  SMART FILAMENT SENSOR - REAL-TIME EXT/RET FEEDBACK & TELEMETRY")
    print("=" * 80)
    print("  Two-Point Diameter Calibration:")
    print("    'e' -> Step 1: Tare empty bearings (no filament -> 0.000 mm)")
    print("    'c' -> Step 2: Calibrate span with measured filament (caliper input)")
    print("    'w' -> Save calibrations permanently to RP2040 Flash")
    print("\n  Extrusion Feedback & Controls:")
    print("    'z' -> Zero distance counter and reset peak speed/flow stats")
    print("    'p' -> Print peak extrusion / retraction speed & volumetric flow stats")
    print("    'd' -> Toggle raw ASCII stream from Pico")
    print("    'b' -> Jump to Katapult bootloader")
    print("    Ctrl+C -> Exit")
    print("=" * 80 + "\n")

    missed_count = 0
    buffer = bytearray()

    max_extrude_spd = 0.0   # mm/s
    max_retract_spd = 0.0   # mm/s (negative)
    max_flow_rate   = 0.0   # mm3/s
    last_known_dia  = 1.750 # mm

    try:
        while True:
            # Check for user keyboard input (non-blocking)
            if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                cmd = sys.stdin.readline().strip().lower()
                if cmd == 'e':
                    # Tare empty bearings (0.000 mm)
                    ser.write(bytearray([0xF5, 0x22]))
                    ser.write(b'e')
                    print("\n[CMD] Tare empty bearings -> Zero reference set & saved (0.000 mm).")
                elif cmd == 'c':
                    # Calibrate span with custom caliper measurement
                    print("\n" + "-" * 60)
                    print("  FILAMENT SPAN CALIBRATION")
                    print("  Measure your test filament with calipers.")
                    sys.stdout.write("  Enter measured diameter in mm [press Enter for 1.75]: ")
                    sys.stdout.flush()
                    val_line = sys.stdin.readline().strip()
                    val_mm = 1.75
                    if val_line:
                        try:
                            val_mm = float(val_line)
                        except ValueError:
                            print(f"  [ERROR] '{val_line}' is not a valid number. Calibration cancelled.")
                            continue
                    cal_um = int(round(val_mm * 1000.0))
                    # Send binary CMD_CAL_SPAN: 0xF5 0x23 <lo> <hi>
                    ser.write(bytearray([0xF5, 0x23, cal_um & 0xFF, (cal_um >> 8) & 0xFF]))
                    # Also send ASCII fallback
                    ser.write(f"c {val_mm:.3f}\n".encode('ascii'))
                    print(f"  [SUCCESS] Span calibrated to {val_mm:.3f} mm ({cal_um} um) & saved.")
                    print("-" * 60 + "\n")
                elif cmd == 'w':
                    ser.write(bytearray([0xF5, 0x24]))
                    ser.write(b'w')
                    print("\n[CMD] Saved all calibration parameters to RP2040 Flash memory.")
                elif cmd == 'z':
                    ser.write(b'z')
                    max_extrude_spd = 0.0
                    max_retract_spd = 0.0
                    max_flow_rate = 0.0
                    print("\n[CMD] Zeroed motion distance & reset peak speed/flow stats.")
                elif cmd == 'p':
                    nom_area = math.pi * ((1.75 / 2.0) ** 2)
                    act_area = math.pi * ((last_known_dia / 2.0) ** 2) if last_known_dia > 0.5 else nom_area
                    flow_trim = (nom_area / act_area) * 100.0 if act_area > 0 else 100.0
                    print("\n" + "=" * 65)
                    print("  PEAK EXTRUSION & FLOW FEEDBACK STATISTICS")
                    print("=" * 65)
                    print(f"  Max Extrusion Speed:  {max_extrude_spd:+6.2f} mm/s")
                    print(f"  Max Volumetric Flow:  {max_flow_rate:+6.2f} mm³/s")
                    print(f"  Max Retraction Speed: {max_retract_spd:+6.2f} mm/s")
                    print(f"  Current Diameter:     {last_known_dia:6.3f} mm (Area: {act_area:.3f} mm²)")
                    print(f"  Ideal Flow Multiplier:{flow_trim:6.1f}% (to match nominal 1.75mm)")
                    print("=" * 65 + "\n")
                elif cmd == 'd':
                    ser.write(b'd')
                    print("\n[CMD] Sent: Toggle ASCII stream.")
                elif cmd == 'b':
                    ser.write(b'b')
                    print("\n[CMD] Sent: Jump to Katapult Bootloader.")
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
                missed_count = 0
                continue

            # Check for new 33-byte binary response
            packet_found = False
            while len(buffer) >= 33:
                # Find header 0x05, 0xFF, 0x10
                idx = buffer.find(b'\x05\xff\x10')
                if idx == -1:
                    # No header in buffer, keep only last 2 bytes in case header was split
                    buffer = buffer[-2:]
                    break
                if idx > 0:
                    # Discard bytes before header
                    buffer = buffer[idx:]

                if len(buffer) < 33:
                    break

                # Extract packet
                payload = buffer[3:33]
                buffer = buffer[33:]
                packet_found = True
                missed_count = 0

                (motion_mag, dia_mag, present, fault_flags,
                 motion_turns, motion_ang, total_counts, total_um,
                 velocity_um_s, dia_raw_ang, dia_filtered_um, dia_variance_um) = struct.unpack('<BBBBllllhlhh', payload)

                motion_str = MAGNET_STATES.get(motion_mag, f"MAG:{motion_mag}")
                dia_str = MAGNET_STATES.get(dia_mag, f"MAG:{dia_mag}")
                sw_str = "PRESENT" if present else "RUNOUT"
                fault_str = decode_faults(fault_flags)

                pos_mm = total_um / 1000.0
                speed_mm_s = velocity_um_s / 1000.0
                dia_mm = dia_filtered_um / 1000.0
                ripple_mm = dia_variance_um / 1000.0

                if dia_mm > 0.5:
                    last_known_dia = dia_mm
                    act_area = math.pi * ((dia_mm / 2.0) ** 2)
                    nom_area = math.pi * ((1.75 / 2.0) ** 2)
                    area_pct = (act_area / nom_area) * 100.0
                    flow_mm3_s = speed_mm_s * act_area
                else:
                    act_area = 0.0
                    area_pct = 0.0
                    flow_mm3_s = 0.0

                # Track peak session speeds
                if speed_mm_s > max_extrude_spd:
                    max_extrude_spd = speed_mm_s
                    max_flow_rate = flow_mm3_s
                elif speed_mm_s < max_retract_spd:
                    max_retract_spd = speed_mm_s

                # Motion State
                if speed_mm_s > 0.4:
                    dir_str = "EXTRUDE"
                elif speed_mm_s < -0.4:
                    dir_str = "RETRACT"
                else:
                    dir_str = "IDLE   "

                # Compact status tag to prevent terminal line-wrap glitch
                if fault_flags & 0x01:
                    status_str = "STALL!"
                elif not present:
                    status_str = "RUNOUT"
                elif fault_flags & 0x04:
                    status_str = "OUT-OF-SPEC"
                else:
                    status_str = "OK"

                dia_str = f"{dia_mm:5.3f}mm ({area_pct:5.1f}% nom)" if present else "0.000mm"

                line_content = (
                    f"[POS]: {pos_mm:+7.2f}mm "
                    f"| [SPD]: {speed_mm_s:+6.1f}mm/s ({dir_str}) "
                    f"| [FLOW]: {flow_mm3_s:+6.1f}mm³/s "
                    f"| [DIA]: {dia_str} "
                    f"| [{status_str}]"
                )

                # Auto-fit to terminal width so it never wraps to next line
                term_width = shutil.get_terminal_size(fallback=(120, 24)).columns
                if len(line_content) >= term_width:
                    line_content = line_content[:term_width - 1]

                sys.stdout.write(f"\r\033[K{line_content}")
                sys.stdout.flush()

            # Fallback for legacy 18-byte packet
            if not packet_found and len(buffer) >= 18:
                idx = buffer.find(b'\x05\xff\x10')
                if idx != -1 and len(buffer) >= idx + 18:
                    legacy_payload = buffer[idx + 3: idx + 18]
                    buffer = buffer[idx + 18:]
                    (motion_mag, dia_mag, present,
                     motion_turns, motion_ang, dia_ang) = struct.unpack('<BBblll', legacy_payload)
                    sys.stdout.write(f"\r[LEGACY] Turns: {motion_turns} | MotionAng: {motion_ang} | DiaAng: {dia_ang}   ")
                    sys.stdout.flush()
                    missed_count = 0
                    packet_found = True

            if not packet_found:
                missed_count += 1
                if missed_count > 15 and missed_count % 20 == 0:
                    sys.stdout.write("\r[WAITING] No telemetry packets received yet... (Have you flashed the updated binary?)   ")
                    sys.stdout.flush()

            time.sleep(0.05) # 20 Hz query loop

    except KeyboardInterrupt:
        print("\n\nExiting live monitor.")
    finally:
        ser.close()

if __name__ == '__main__':
    main()
