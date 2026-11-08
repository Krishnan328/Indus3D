#!/usr/bin/env python3
"""
Indus3D ESP8266 Bed Collision Monitor & Chamber Telemetry Daemon
================================================================
Monitors real-time bed acceleration, instantaneous jerk delta, and chamber
environmental telemetry (Temperature, Humidity, Barometric Pressure).
Logs historical trends to CSV, alerts on crash detection, and triggers
fail-safe emergency pause routines.

Author: Krishnan H (Indus3D Project)
"""

import sys
import os
import time
import argparse
import requests
import csv
from datetime import datetime
import serial
import json
import glob
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

def find_serial_port():
    """Auto-detects USB serial device for ESP8266."""
    # Explicitly exclude Klipper ports and the ATmega mainboard (ttyUSB0)
    all_c = glob.glob("/dev/serial/by-id/*") + glob.glob("/dev/serial/by-path/*")
    candidates = [
        c for c in all_c
        if 'Klipper' not in c and 'usb-0:2.2:1.0' not in c and 'A5069RR4' not in c
    ]
    return candidates[0] if candidates else None


class BedMonitorDaemon:
    def __init__(self, ip=None, serial_port=None, baud=115200, poll_sec=1.0, log_file=None, api_port=7127, moonraker_url="http://127.0.0.1:7125", show_dashboard=True):
        self.ip = ip
        self.serial_port = serial_port
        self.baud = baud
        self.poll_sec = poll_sec
        self.log_file = log_file
        self.api_port = api_port
        self.moonraker_url = moonraker_url.rstrip("/") if moonraker_url else None
        self.show_dashboard = show_dashboard
        self.running = True
        self.crash_latched = False
        self.last_crash_alert_time = 0
        self.lock = threading.Lock()
        self.serial_lock = threading.Lock()
        self.serial_conn = None
        self.latest_data = {
            "connected": False,
            "chamber": {"temp_c": None, "humidity_pct": None, "pressure_hpa": None},
            "bed_accel": {"x_mg": 0, "y_mg": 0, "z_mg": 0, "jerk_mg": 0},
            "crash_detected": False,
            "uptime_sec": 0
        }

        # Setup CSV logger if requested
        if self.log_file:
            init_header = not os.path.exists(self.log_file)
            self.csv_f = open(self.log_file, "a", newline="", encoding="utf-8")
            self.writer = csv.writer(self.csv_f)
            if init_header:
                self.writer.writerow([
                    "timestamp_iso", "uptime_sec", "accel_x_mg", "accel_y_mg", "accel_z_mg",
                    "jerk_mg", "temp_c", "humidity_pct", "pressure_hpa", "crash_detected"
                ])
                self.csv_f.flush()
        else:
            self.csv_f = None
            self.writer = None

    def start_http_server(self):
        daemon_self = self

        class HubHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress HTTP access logging in daemon console

            def do_GET(self):
                clean_path = self.path.split('?')[0]
                if clean_path in ["/telemetry", "/status", "/api/telemetry"]:
                    with daemon_self.lock:
                        payload = json.dumps(daemon_self.latest_data, indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(payload)
                elif clean_path in ["/chamber", "/api/chamber"]:
                    with daemon_self.lock:
                        payload = json.dumps(daemon_self.latest_data.get("chamber", {}), indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                clean_path = self.path.split('?')[0]
                if clean_path in ["/reset_crash", "/api/reset_crash"]:
                    ok = daemon_self.reset_crash()
                    self.send_response(200 if ok else 500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": ok}).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

        try:
            server = HTTPServer(("0.0.0.0", self.api_port), HubHandler)
            print(f"[DAEMON] HTTP REST API listening on http://0.0.0.0:{self.api_port}/telemetry")
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
        except Exception as e:
            print(f"[WARN] Could not bind HTTP server on port {self.api_port}: {e}")

    def reset_crash(self):
        """Sends RESET_CRASH to ESP8266 and unlatches local state."""
        self.crash_latched = False
        acquired = self.serial_lock.acquire(timeout=0.25)
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.write(b"RESET_CRASH\n")
                self.serial_conn.flush()
        except Exception as e:
            print(f"[ERROR] Failed to send RESET_CRASH: {e}")
        finally:
            if acquired:
                self.serial_lock.release()
        return True

    def fetch_http_telemetry(self):
        """Queries the /telemetry JSON endpoint on ESP8266."""
        url = f"http://{self.ip}/telemetry"
        try:
            resp = requests.get(url, timeout=1.5)
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
        return None

    def render_dashboard(self, data):
        """Renders real-time terminal dashboard with ANSI styling."""
        if "error" in data:
            print(f"\r[{datetime.now().strftime('%H:%M:%S')}] Connecting to ESP8266 ({self.ip})... {data['error']}", end="", flush=True)
            return

        bed = data.get("bed_accel", {})
        chamber = data.get("chamber", {})
        crash = data.get("crash_detected", False)
        uptime = data.get("uptime_sec", 0)

        # Clear line and print dashboard block
        sys.stdout.write("\033[H\033[J") # ANSI clear screen
        print("=" * 68)
        print(" Indus3D ESP8266 Bed Collision & Chamber Telemetry Monitor")
        print("=" * 68)
        print(f" Target Host:   http://{self.ip}  |  Uptime: {uptime} s")
        print("-" * 68)

        # Chamber section
        t_c = chamber.get("temp_c")
        h_pct = chamber.get("humidity_pct")
        p_hpa = chamber.get("pressure_hpa")
        t_str = f"{t_c:.1f} °C" if t_c is not None else "N/A"
        h_str = f"{h_pct:.1f} %" if h_pct is not None else "N/A"
        p_str = f"{p_hpa:.1f} hPa" if p_hpa is not None else "N/A"
        print(f" Chamber Temp:  {t_str:<10}  | Humidity: {h_str:<8} | Pressure: {p_str}")

        # Bed acceleration & Jerk section
        x_mg = bed.get("x_mg", 0)
        y_mg = bed.get("y_mg", 0)
        z_mg = bed.get("z_mg", 0)
        jerk = bed.get("jerk_mg", 0)
        print(f" Bed Accel:     X={x_mg:+5d} mg  | Y={y_mg:+5d} mg  | Z={z_mg:+5d} mg")
        print(f" Current Jerk:  {jerk:5d} mg   (Instantaneous 3-axis delta)")
        print("-" * 68)

        # Crash Status
        if crash:
            print("\033[1;31m [STATUS] CRITICAL: BED COLLISION / CRASH LATCHED!\033[0m")
            crash_info = data.get("crash_info", {})
            if crash_info:
                print(f" Peak Jerk:     \033[1;31m{crash_info.get('peak_jerk_mg', 0)} mg\033[0m")
        else:
            print("\033[1;32m [STATUS] Bed Normal (Monitoring at 200 Hz)\033[0m")

        print("=" * 68)
        print(" Press Ctrl+C to exit monitor daemon.")
        sys.stdout.flush()

    def check_crash_alert(self, data):
        """Triggers local console alert and sends BED_CRASH_HANDLER to Moonraker if a crash is detected."""
        crash = data.get("crash_detected", False)
        if crash and not self.crash_latched:
            self.crash_latched = True
            now = time.time()
            if now - self.last_crash_alert_time > 5.0:
                self.last_crash_alert_time = now
                jerk = data.get("bed_accel", {}).get("jerk_mg", 2000)
                sys.stdout.write('\a') # System bell
                sys.stdout.flush()
                print("\n\n" + "!" * 68)
                print(f">>> EMERGENCY: BED CRASH DETECTED ON Y-CARRIAGE! (Jerk={jerk} mg) <<<")
                print("!" * 68 + "\n")

                if self.moonraker_url:
                    try:
                        resp = requests.post(
                            f"{self.moonraker_url}/printer/gcode/script",
                            json={"script": f"BED_CRASH_HANDLER JERK={jerk}"},
                            timeout=1.5
                        )
                        if resp.status_code == 200:
                            print("[MOONRAKER] Successfully triggered BED_CRASH_HANDLER macro!")
                    except Exception as e:
                        print(f"[WARN] Failed to trigger Moonraker crash macro: {e}")
        elif not crash:
            self.crash_latched = False

    def log_record(self, data):
        """Writes row to CSV."""
        if not self.writer or "error" in data:
            return
        bed = data.get("bed_accel", {})
        chamber = data.get("chamber", {})
        row = [
            datetime.now().isoformat(),
            data.get("uptime_sec", 0),
            bed.get("x_mg", 0),
            bed.get("y_mg", 0),
            bed.get("z_mg", 0),
            bed.get("jerk_mg", 0),
            chamber.get("temp_c", ""),
            chamber.get("humidity_pct", ""),
            chamber.get("pressure_hpa", ""),
            data.get("crash_detected", False)
        ]
        self.writer.writerow(row)
        self.csv_f.flush()

    def run_http_loop(self):
        self.start_http_server()
        print(f"[DAEMON] Starting HTTP telemetry monitoring loop for {self.ip}...")
        while self.running:
            try:
                data = self.fetch_http_telemetry()
                if data:
                    with self.lock:
                        self.latest_data = {**data, "connected": True}
                    if self.show_dashboard:
                        self.render_dashboard(data)
                    self.check_crash_alert(data)
                    self.log_record(data)
                time.sleep(self.poll_sec)
            except KeyboardInterrupt:
                print("\n[DAEMON] Shutting down.")
                break
            except Exception as e:
                print(f"\n[DAEMON] Exception: {e}")
                time.sleep(2.0)

    def run_serial_loop(self):
        if not self.serial_port or self.serial_port.lower() == "auto":
            self.serial_port = find_serial_port()
            if not self.serial_port:
                print("[ERROR] No USB serial port detected. Please connect ESP8266 or pass --serial <PORT>.")
                sys.exit(1)

        self.start_http_server()
        print(f"[DAEMON] Opening serial connection to {self.serial_port} @ {self.baud} baud...")
        try:
            ser = serial.Serial(self.serial_port, self.baud, timeout=1.0)
            with self.serial_lock:
                self.serial_conn = ser
        except Exception as e:
            print(f"[ERROR] Could not open serial port: {e}")
            sys.exit(1)

        print("[DAEMON] Serial port open. Listening for live telemetry...")
        while self.running:
            try:
                with self.serial_lock:
                    line = ser.readline().decode('utf-8', errors='replace').strip()
                if line:
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            data = json.loads(line)
                            self.ip = f"USB Serial ({self.serial_port})"
                            with self.lock:
                                self.latest_data = {**data, "connected": True}
                            if self.show_dashboard:
                                self.render_dashboard(data)
                            self.check_crash_alert(data)
                            self.log_record(data)
                        except json.JSONDecodeError:
                            if self.show_dashboard:
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] {line}")
                    else:
                        if self.show_dashboard:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] {line}")
                        if "BED_CRASH_DETECTED" in line:
                            self.check_crash_alert({"crash_detected": True, "bed_accel": {"jerk_mg": 2500}})
            except KeyboardInterrupt:
                break
            except Exception as e:
                with self.lock:
                    self.latest_data["connected"] = False
                print(f"[ERROR] Serial read error: {e}")
                time.sleep(1.0)
        ser.close()


def main():
    parser = argparse.ArgumentParser(description="Indus3D ESP8266 Bed Collision & Chamber Telemetry Daemon")
    parser.add_argument("--serial", type=str, default="auto", help="Serial device port (default: auto)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default: 115200)")
    parser.add_argument("--ip", type=str, default=None, help="ESP8266 IP address (optional for Wi-Fi mode)")
    parser.add_argument("--interval", type=float, default=1.0, help="Poll interval in seconds (default: 1.0)")
    parser.add_argument("--log", type=str, default="chamber_telemetry.csv", help="Path to CSV log file")
    parser.add_argument("--port", type=int, default=7127, help="Local REST API port (default: 7127)")
    parser.add_argument("--moonraker", type=str, default="http://127.0.0.1:7125", help="Moonraker URL")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable ncurses dashboard for background systemd running")
    args = parser.parse_args()

    daemon = BedMonitorDaemon(
        ip=args.ip or "127.0.0.1",
        serial_port=args.serial,
        baud=args.baud,
        poll_sec=args.interval,
        log_file=args.log,
        api_port=args.port,
        moonraker_url=args.moonraker,
        show_dashboard=not args.no_dashboard
    )

    if args.ip and not args.serial:
        daemon.run_http_loop()
    else:
        daemon.run_serial_loop()


if __name__ == "__main__":
    main()
