#!/usr/bin/env python3
"""
Mock ESP8266 Multi-Sensor Hub Server
====================================
Simulates the ESP8266 REST API (port 8080 or 80) and High-Speed TCP streaming
(port 8266) with synthetic accelerometer and BME280 telemetry for automated testing.

Author: Krishnan H (Indus3D Project)
"""

import sys
import time
import math
import socket
import struct
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

HTTP_PORT = 8080
TCP_STREAM_PORT = 8266

# ADXL345 constants
SCALE_LSB_PER_G = 256.0 # 3.90625 mg/LSB -> 256 LSB/g

# Global simulated state
sim_state = {
    "uptime_start": time.time(),
    "crash_latched": False,
    "crash_peak_jerk": 0,
    "threshold_mg": 2000,
    "chamber_temp": 26.4,
    "chamber_humidity": 43.1,
    "chamber_pressure": 1012.8,
    "shaper_active": False,
    "shaper_samples_sent": 0
}


class MockHTTPHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        uptime = int(time.time() - sim_state["uptime_start"])

        if self.path == "/telemetry":
            self._set_headers(200)
            payload = {
                "bed_accel": {
                    "x_mg": 145,
                    "y_mg": -12,
                    "z_mg": -980,
                    "jerk_mg": 18
                },
                "chamber": {
                    "temp_c": sim_state["chamber_temp"],
                    "humidity_pct": sim_state["chamber_humidity"],
                    "pressure_hpa": sim_state["chamber_pressure"]
                },
                "crash_detected": sim_state["crash_latched"],
                "uptime_sec": uptime
            }
            if sim_state["crash_latched"]:
                payload["crash_info"] = {
                    "timestamp_ms": 128450,
                    "peak_jerk_mg": sim_state["crash_peak_jerk"],
                    "accel_at_crash": {"x": 120, "y": 2150, "z": -890}
                }
            self.wfile.write(json.dumps(payload).encode('utf-8'))

        elif self.path == "/chamber":
            self._set_headers(200)
            payload = {
                "temperature": sim_state["chamber_temp"],
                "humidity": sim_state["chamber_humidity"],
                "pressure": sim_state["chamber_pressure"]
            }
            self.wfile.write(json.dumps(payload).encode('utf-8'))

        elif self.path == "/status":
            self._set_headers(200)
            payload = {
                "device": "ESP8266-BedHub-MOCK",
                "version": "1.0.0",
                "ip": "127.0.0.1",
                "rssi": -45,
                "adxl345_online": True,
                "bme280_online": True,
                "crash_latched": sim_state["crash_latched"],
                "crash_threshold_mg": sim_state["threshold_mg"],
                "moonraker_target": "127.0.0.1:7125",
                "shaper_active": sim_state["shaper_active"],
                "free_heap": 42100,
                "uptime_sec": uptime
            }
            self.wfile.write(json.dumps(payload).encode('utf-8'))

        elif self.path == "/reset_crash":
            sim_state["crash_latched"] = False
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "ok", "message": "Crash reset"}).encode('utf-8'))

        elif self.path == "/shaper/status":
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "running": sim_state["shaper_active"],
                "samples_recorded": sim_state["shaper_samples_sent"],
                "rate_hz": 1600,
                "duration_s": 5
            }).encode('utf-8'))

        else:
            self._set_headers(404)
            self.wfile.write(b'{"error": "Endpoint not found"}')

    def do_POST(self):
        if self.path == "/reset_crash":
            sim_state["crash_latched"] = False
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "ok", "message": "Crash reset"}).encode('utf-8'))
        elif self.path.startswith("/shaper/start"):
            sim_state["shaper_active"] = True
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "status": "started",
                "rate_hz": 1600,
                "duration_s": 5,
                "tcp_stream_port": TCP_STREAM_PORT
            }).encode('utf-8'))
        else:
            self.do_GET()

    def log_message(self, format, *args):
        pass # Suppress noisy HTTP logs


def start_tcp_stream_server():
    """Simulates high-speed TCP accelerometer stream with 48.5 Hz resonance on Y."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("0.0.0.0", TCP_STREAM_PORT))
    server_sock.listen(1)
    print(f"[MOCK TCP] Server listening on port {TCP_STREAM_PORT}...")

    packet_fmt = "<BBHIhhhB"
    f_res = 48.5 # Primary resonance frequency in Hz

    while True:
        try:
            client, addr = server_sock.accept()
            print(f"[MOCK TCP] Client connected: {addr}. Generating 1600 Hz synthetic resonance stream...")
            sim_state["shaper_active"] = True
            sim_state["shaper_samples_sent"] = 0

            # Stream for 5 seconds at 1600 Hz (8000 samples)
            rate_hz = 1600
            total_samples = 5 * rate_hz
            dt = 1.0 / rate_hz
            start_us = int((time.time() % 3600) * 1e6) % (2**32)

            for i in range(total_samples):
                t = i * dt
                # Synthetic acceleration with 48.5 Hz damped resonance + noise + gravity
                # Y axis has dominant resonance
                decay = math.exp(-0.08 * (t % 1.0) * f_res)
                y_vib = 0.45 * math.sin(2 * math.pi * f_res * t) * decay
                y_noise = (math.sin(17 * t) + math.cos(31 * t)) * 0.03
                x_accel = 0.02 * math.sin(2 * math.pi * 32.0 * t)
                y_accel = y_vib + y_noise - 0.02 # tiny DC offset
                z_accel = -1.0 + 0.01 * math.sin(2 * math.pi * 10 * t) # ~1g gravity on Z

                # Convert to raw int16 LSB
                x_raw = int(x_accel * SCALE_LSB_PER_G)
                y_raw = int(y_accel * SCALE_LSB_PER_G)
                z_raw = int(z_accel * SCALE_LSB_PER_G)
                time_us = start_us + int(t * 1e6)

                # Pack 14 bytes to calculate checksum
                pkt_data = struct.pack("<BBHIhhh", 0xAA, 0x55, i % 65536, time_us, x_raw, y_raw, z_raw)
                chk = 0
                for b in pkt_data:
                    chk ^= b
                full_pkt = pkt_data + struct.pack("B", chk)

                client.sendall(full_pkt)
                sim_state["shaper_samples_sent"] += 1

                # Pace samples to approximate 1600 Hz in batches
                if i % 32 == 0:
                    time.sleep(32 * dt * 0.8)

            client.close()
            sim_state["shaper_active"] = False
            print(f"[MOCK TCP] Finished sending {total_samples} samples.")
        except Exception as e:
            print(f"[MOCK TCP] Stream error: {e}")
            break


def main():
    tcp_thread = threading.Thread(target=start_tcp_stream_server, daemon=True)
    tcp_thread.start()

    http_server = HTTPServer(("0.0.0.0", HTTP_PORT), MockHTTPHandler)
    print(f"[MOCK HTTP] Server running at http://127.0.0.1:{HTTP_PORT}")
    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("\n[MOCK] Stopping servers.")
        http_server.server_close()


if __name__ == "__main__":
    main()
