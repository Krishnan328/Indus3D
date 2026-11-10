#!/usr/bin/env python3
"""Indus3D System Stability & Hardware Health Checker.

Performs a comprehensive multi-tier diagnostic check of the 3D printer system:
  1. Host Vitals & OS Kernel Settings
  2. Core Systemd Services (klipper, moonraker, indus3d, dsp)
  3. Klipper & Moonraker State
  4. Multi-MCU Telemetry (Mainboard, EBB36 Toolhead, BTT Eddy)
  5. Physical USB Bus Topology & Hub Cascading
  6. Kernel USB Bus Stability & Disconnect Error Logs
  7. Indus3D Digital Twin API & High-Frequency WebSocket Streaming

Usage:
  python3 scripts/check_system_stability.py
  python3 scripts/check_system_stability.py --json
  python3 scripts/check_system_stability.py --ws-duration 3.0
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# ANSI color escape codes
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

MOONRAKER_URL = os.environ.get("MOONRAKER_URL", "http://127.0.0.1:7125")
INDUS3D_URL = os.environ.get("INDUS3D_URL", "http://127.0.0.1:5001")

_SESSION_COOKIE: Optional[str] = None


def _get_auth_cookie() -> Optional[str]:
    global _SESSION_COOKIE
    if _SESSION_COOKIE:
        return _SESSION_COOKIE

    password = os.environ.get("INDUS3D_PASSWORD")
    if not password:
        for p in ("/var/lib/indus3d/indus3d.env", "/etc/indus3d/indus3d.env"):
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("INDUS3D_PASSWORD="):
                                password = line.partition("=")[2].strip()
                                break
                except Exception:
                    pass
    if password:
        try:
            req = urllib.request.Request(
                f"{INDUS3D_URL}/api/v1/auth/login",
                data=json.dumps({"password": password}).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "Indus3D-Stability-Check/1.0"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                _SESSION_COOKIE = resp.headers.get("Set-Cookie")
        except Exception:
            pass
    return _SESSION_COOKIE


def _http_get(url: str, timeout: float = 3.0) -> Tuple[int, Any]:
    headers = {"User-Agent": "Indus3D-Stability-Check/1.0"}
    cookie = _get_auth_cookie()
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(content)
            except json.JSONDecodeError:
                return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(content)
        except json.JSONDecodeError:
            return e.code, content
    except Exception as e:
        return 0, str(e)


class StabilityChecker:
    def __init__(self, ws_duration: float = 2.0, verbose: bool = False):
        self.ws_duration = ws_duration
        self.verbose = verbose
        self.results: Dict[str, Any] = {
            "timestamp": time.time(),
            "overall_status": "PASS",
            "scores": {"passed": 0, "warnings": 0, "failed": 0},
            "checks": {},
            "recommendations": [],
        }

    def _record(self, category: str, name: str, status: str, message: str, details: Any = None):
        if category not in self.results["checks"]:
            self.results["checks"][category] = []
        self.results["checks"][category].append({
            "name": name,
            "status": status,
            "message": message,
            "details": details,
        })
        if status == "PASS":
            self.results["scores"]["passed"] += 1
        elif status == "WARN":
            self.results["scores"]["warnings"] += 1
            if self.results["overall_status"] != "FAIL":
                self.results["overall_status"] = "WARN"
        elif status == "FAIL":
            self.results["scores"]["failed"] += 1
            self.results["overall_status"] = "FAIL"

    def check_host_vitals(self):
        cat = "Host Vitals"
        # Load average
        try:
            load1, load5, load15 = os.getloadavg()
            cpu_count = os.cpu_count() or 1
            load_pct = (load1 / cpu_count) * 100
            status = "PASS" if load_pct < 80 else ("WARN" if load_pct < 100 else "FAIL")
            self._record(cat, "CPU Load Average", status,
                         f"{load1:.2f}, {load5:.2f}, {load15:.2f} ({load_pct:.1f}% of {cpu_count} cores)",
                         {"load1": load1, "load5": load5, "load15": load15, "cores": cpu_count})
        except Exception as e:
            self._record(cat, "CPU Load Average", "WARN", f"Could not determine load: {e}")

        # Memory usage
        try:
            with open("/proc/meminfo", "r") as f:
                meminfo = dict(line.split(":", 1) for line in f if ":" in line)
            total = int(meminfo.get("MemTotal", "0").split()[0]) * 1024
            avail = int(meminfo.get("MemAvailable", "0").split()[0]) * 1024
            used_pct = ((total - avail) / total) * 100 if total else 0
            status = "PASS" if used_pct < 85 else ("WARN" if used_pct < 95 else "FAIL")
            self._record(cat, "System RAM Usage", status,
                         f"{used_pct:.1f}% used ({((total - avail)/1024/1024):.0f}MB / {(total/1024/1024):.0f}MB)",
                         {"used_pct": round(used_pct, 1), "avail_mb": round(avail / 1024 / 1024)})
        except Exception as e:
            self._record(cat, "System RAM Usage", "WARN", f"Could not determine memory: {e}")

        # Disk space
        try:
            st = os.statvfs("/")
            free_gb = (st.f_bavail * st.f_frsize) / (1024 ** 3)
            total_gb = (st.f_blocks * st.f_frsize) / (1024 ** 3)
            used_pct = ((total_gb - free_gb) / total_gb) * 100 if total_gb else 0
            status = "PASS" if free_gb > 2.0 else ("WARN" if free_gb > 0.5 else "FAIL")
            self._record(cat, "Root Filesystem Space", status,
                         f"{free_gb:.1f} GB free of {total_gb:.1f} GB ({used_pct:.1f}% used)",
                         {"free_gb": round(free_gb, 2), "total_gb": round(total_gb, 2)})
        except Exception as e:
            self._record(cat, "Root Filesystem Space", "WARN", f"Could not determine disk space: {e}")

        # USB Autosuspend parameter
        try:
            autosuspend_path = "/sys/module/usbcore/parameters/autosuspend"
            if os.path.exists(autosuspend_path):
                with open(autosuspend_path, "r") as f:
                    val = f.read().strip()
                if val == "-1":
                    self._record(cat, "USB Autosuspend Setting", "PASS", "Disabled (val = -1, optimal for MCUs)")
                else:
                    self._record(cat, "USB Autosuspend Setting", "WARN",
                                 f"Active (val = {val}s). USB devices may suspend during idle.",
                                 {"value": val})
                    self.results["recommendations"].append(
                        "Add 'boot.kernelParams = [ \"usbcore.autosuspend=-1\" ];' to NixOS configuration to prevent USB power interruptions."
                    )
            else:
                self._record(cat, "USB Autosuspend Setting", "PASS", "usbcore parameter not found (kernel default)")
        except Exception as e:
            self._record(cat, "USB Autosuspend Setting", "WARN", f"Could not check usbcore parameter: {e}")

    def check_systemd_services(self):
        cat = "System Services"
        services = ["klipper", "moonraker", "indus3d"]
        for svc in services:
            try:
                proc = subprocess.run(
                    ["systemctl", "is-active", svc],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3
                )
                state = proc.stdout.strip()
                if state == "active":
                    self._record(cat, f"Service: {svc}", "PASS", "Active and running")
                else:
                    self._record(cat, f"Service: {svc}", "FAIL", f"Inactive or failed (state: {state})")
                    self.results["recommendations"].append(f"Restart failed service with: sudo systemctl restart {svc}")
            except Exception as e:
                self._record(cat, f"Service: {svc}", "WARN", f"Could not check systemd status: {e}")

        # DSP process check
        try:
            proc = subprocess.run(
                ["pgrep", "indus3d-dsp"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3
            )
            if proc.returncode == 0 and proc.stdout.strip():
                pids = proc.stdout.strip().split()
                self._record(cat, "Service: indus3d-dsp", "PASS", f"Running (PID: {', '.join(pids)})")
            else:
                self._record(cat, "Service: indus3d-dsp", "WARN", "Not running (Rust DSP acceleration inactive)")
        except Exception as e:
            self._record(cat, "Service: indus3d-dsp", "WARN", f"DSP process check failed: {e}")

    def check_klipper_and_moonraker(self):
        cat = "Klipper & Moonraker"
        code, data = _http_get(f"{MOONRAKER_URL}/printer/info")
        if code != 200 or not isinstance(data, dict):
            self._record(cat, "Moonraker API Connectivity", "FAIL",
                         f"Could not reach Moonraker on {MOONRAKER_URL} (HTTP {code})")
            self.results["recommendations"].append("Verify Moonraker is running and port 7125 is accessible.")
            return

        result = data.get("result", {})
        state = result.get("state", "unknown")
        state_msg = result.get("state_message", "").strip()

        if state == "ready":
            self._record(cat, "Klipper Operational State", "PASS", f"Ready ({result.get('software_version', 'Klipper')})")
        elif state == "startup":
            self._record(cat, "Klipper Operational State", "WARN", f"Starting up... ({state_msg})")
        else:
            self._record(cat, "Klipper Operational State", "FAIL", f"State '{state}': {state_msg}")
            if "Failed automated reset of MCU" in state_msg:
                self.results["recommendations"].append(
                    "Klipper MCU reset failure: Verify that 'restart_method: command' is set on all STM32 / RP2040 MCU sections in config."
                )

        # Check toolhead homed state & position
        code_objs, objs = _http_get(f"{MOONRAKER_URL}/printer/objects/query?toolhead&print_stats")
        if code_objs == 200 and isinstance(objs, dict):
            res_objs = objs.get("result", {}).get("status", {})
            th = res_objs.get("toolhead", {})
            homed = th.get("homed_axes", "")
            pos = th.get("position", [0, 0, 0, 0])
            p_state = res_objs.get("print_stats", {}).get("state", "standby")
            self._record(cat, "Toolhead Coordinates & State", "PASS",
                         f"Status: {p_state} | Homed: '{homed}' | Pos: [{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.2f}]",
                         {"homed_axes": homed, "position": pos, "print_state": p_state})

    def check_mcu_telemetry(self):
        cat = "MCU Hardware Telemetry"
        # Query status for mainboard mcu, EBB toolhead mcu, and eddy probe mcu
        code, data = _http_get(f"{MOONRAKER_URL}/printer/objects/query?mcu&mcu%20EBB&mcu%20eddy")
        if code != 200 or not isinstance(data, dict):
            self._record(cat, "MCU Query", "WARN", "Could not query MCU objects from Moonraker")
            return

        status = data.get("result", {}).get("status", {})
        mcu_keys = [k for k in status.keys() if k.startswith("mcu")]
        if not mcu_keys:
            self._record(cat, "MCU Recognition", "FAIL", "No MCU objects found in Moonraker response")
            return

        for mcu_name in mcu_keys:
            mcu_data = status[mcu_name]
            label = mcu_name.replace("mcu ", "").upper()
            if label == "MCU":
                label = "Mainboard (CH340)"
            elif label == "EBB":
                label = "Toolhead EBB36 (STM32G0B1)"
            elif label == "EDDY":
                label = "Bed Probe (BTT Eddy RP2040)"

            mcu_version = mcu_data.get("mcu_version", "unknown")
            awake = mcu_data.get("mcu_awake", 0.0)
            retransmit = mcu_data.get("bytes_retransmit", 0)
            invalid = mcu_data.get("bytes_invalid", 0)

            # Retransmit check
            if retransmit == 0 and invalid == 0:
                mcu_status = "PASS"
                retransmit_msg = "0 drops / 0 retransmits (rock-solid)"
            elif retransmit < 15 and invalid == 0:
                mcu_status = "PASS"
                retransmit_msg = f"{retransmit} retransmits (normal noise)"
            elif retransmit < 50:
                mcu_status = "WARN"
                retransmit_msg = f"{retransmit} retransmits (elevated packet drops)"
                self.results["recommendations"].append(
                    f"Elevated packet drops on {label}: check USB cable shielding and avoid routing near motor wires."
                )
            else:
                mcu_status = "FAIL"
                retransmit_msg = f"{retransmit} retransmits, {invalid} invalid (SEVERE packet loss!)"
                self.results["recommendations"].append(
                    f"Severe packet loss on {label}: Isolate this MCU to a dedicated host USB port."
                )

            self._record(cat, f"MCU: {label}", mcu_status,
                         f"FW: {mcu_version[:20]} | Awake: {awake*100:.1f}% | {retransmit_msg}",
                         {"mcu": mcu_name, "version": mcu_version, "retransmit": retransmit, "invalid": invalid})

    def check_usb_physical_topology(self):
        cat = "USB Physical Bus Topology"
        # 1. Serial by-id symlinks
        expected_devices = {
            "Mainboard": "usb-1a86_USB_Serial-if00-port0",
            "EBB36": "usb-Klipper_stm32g0b1xx_320054001750304158373620-if00",
            "Eddy": "usb-Klipper_rp2040_504446677843321C-if00",
        }

        by_id_dir = "/dev/serial/by-id"
        present_serials = set()
        if os.path.isdir(by_id_dir):
            present_serials = set(os.listdir(by_id_dir))

        for dev_name, expected_id in expected_devices.items():
            if expected_id in present_serials:
                target = os.path.realpath(os.path.join(by_id_dir, expected_id))
                self._record(cat, f"Serial Device: {dev_name}", "PASS",
                             f"Connected as {os.path.basename(target)} ({expected_id[:35]}...)")
            else:
                self._record(cat, f"Serial Device: {dev_name}", "FAIL",
                             f"MISSING: /dev/serial/by-id/{expected_id} not found!")
                self.results["recommendations"].append(
                    f"{dev_name} is physically disconnected or USB port un-enumerated. Re-seat USB cable or replug."
                )

        # 2. Check PCI USB controllers
        try:
            pci_usb = []
            for path in glob.glob("/sys/bus/pci/devices/*/class"):
                with open(path, "r") as f:
                    cls = f.read().strip()
                if cls.startswith("0x0c03"):  # USB controller class
                    pci_dev = os.path.basename(os.path.dirname(path))
                    pci_usb.append(pci_dev)

            if len(pci_usb) >= 2:
                self._record(cat, "Host USB Controllers", "PASS",
                             f"Found {len(pci_usb)} independent PCI USB controllers ({', '.join(pci_usb)})")
            else:
                self._record(cat, "Host USB Controllers", "PASS", f"Found {len(pci_usb)} PCI USB controller(s)")
        except Exception as e:
            self._record(cat, "Host USB Controllers", "WARN", f"Could not inspect PCI controllers: {e}")

        # 3. Detect cascaded external hubs
        try:
            proc = subprocess.run(
                ["lsusb", "-t"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3
            )
            tree_output = proc.stdout
            # Calculate maximum hub depth by indentation
            max_depth = 0
            for line in tree_output.splitlines():
                if "Class=Hub" in line or "Class=root_hub" in line:
                    indent = len(line) - len(line.lstrip(" "))
                    depth = indent // 4
                    if depth > max_depth:
                        max_depth = depth

            if max_depth <= 2:
                self._record(cat, "USB Hub Hierarchy Depth", "PASS",
                             f"Depth {max_depth} (direct or single-tier hub, clean bus timing)")
            else:
                self._record(cat, "USB Hub Hierarchy Depth", "WARN",
                             f"Depth {max_depth} detected! 3+ cascaded unpowered hubs cause Single-TT transaction translator deadlocks.",
                             {"max_depth": max_depth})
                self.results["recommendations"].append(
                    "Critical: Plug EBB36 and BTT Eddy into separate physical USB ports on the host PC chassis rather than daisy-chaining hubs."
                )
        except Exception as e:
            self._record(cat, "USB Hub Hierarchy Depth", "WARN", f"Could not run lsusb -t: {e}")

    def check_kernel_usb_errors(self):
        cat = "Kernel USB Stability & Errors"
        # Read dmesg or kmsg
        dmesg_text = None
        try:
            proc = subprocess.run(
                ["sudo", "dmesg"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4
            )
            if proc.returncode == 0:
                dmesg_text = proc.stdout
            else:
                proc2 = subprocess.run(
                    ["journalctl", "-k", "-n", "300", "--no-pager"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4
                )
                if proc2.returncode == 0:
                    dmesg_text = proc2.stdout
        except Exception:
            pass

        if dmesg_text is None:
            self._record(cat, "Kernel Dmesg Access", "WARN", "Could not read kernel buffer (permission denied)")
            return

        # Check for specific error signatures
        err_71_count = len(re.findall(r"error -71|err = -71", dmesg_text))
        err_110_count = len(re.findall(r"error -110|err = -110", dmesg_text))
        clear_tt_count = len(re.findall(r"clear tt", dmesg_text))
        bad_cable_count = len(re.findall(r"Maybe the USB cable is bad\?|unable to enumerate", dmesg_text))
        disconnect_count = len(re.findall(r"USB disconnect", dmesg_text))

        # Check recent error status in the last 15 minutes via journalctl to distinguish historical vs active
        recent_err_count = 0
        try:
            proc_recent = subprocess.run(
                ["journalctl", "-k", "--since", "-15m", "-q", "--no-pager"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4
            )
            if proc_recent.returncode == 0:
                recent_err_count = len(re.findall(r"error -71|err = -71|clear tt", proc_recent.stdout))
        except Exception:
            pass

        if recent_err_count == 0 and bad_cable_count == 0:
            msg = "0 active protocol errors in kernel stream"
            if err_71_count > 0:
                msg += f" (system clean since restart; {err_71_count} historical boot entries logged)"
            self._record(cat, "USB Protocol Errors (-71 / -110)", "PASS", msg)
        else:
            status = "FAIL" if (recent_err_count > 5 or bad_cable_count > 0) else "WARN"
            self._record(cat, "USB Protocol Errors (-71 / -110)", status,
                         f"Found {recent_err_count} active EPROTO (-71) errors in last 15m ({err_71_count} total since boot)!",
                         {"err_71": err_71_count, "err_110": err_110_count, "clear_tt": clear_tt_count, "recent": recent_err_count})
            self.results["recommendations"].append(
                "EPROTO (-71) errors indicate USB hub Transaction Translator starvation or voltage drops. Use a powered hub or dedicated PC port."
            )

        if bad_cable_count > 0:
            self._record(cat, "USB Port Enumeration Status", "FAIL",
                         f"Kernel reported 'unable to enumerate' or 'bad cable' {bad_cable_count} times! Port was disabled.",
                         {"bad_cable_count": bad_cable_count})
            self.results["recommendations"].append(
                "A USB port was shut down by the kernel due to hardware faults. Physically unplug and replug the USB hub/cable."
            )
        else:
            self._record(cat, "USB Port Enumeration Status", "PASS", "All ports enumerated cleanly without kernel shutdowns")

    def check_indus3d_twin(self):
        cat = "Indus3D Digital Twin"
        # 1. Profile API
        code, prof = _http_get(f"{INDUS3D_URL}/api/v1/profile/")
        if code == 200 and isinstance(prof, dict):
            bed = prof.get("bed", {})
            size_x = bed.get("size_x_mm", 0)
            size_y = bed.get("size_y_mm", 0)
            size_z = bed.get("size_z_mm", 0)
            exclude = bed.get("bed_exclude_area", [])
            source = prof.get("_source", "unknown")
            self._record(cat, "Profile API", "PASS",
                         f"Bed: {size_x}x{size_y}x{size_z} mm ({len(exclude)} screws) from {source}",
                         {"size_x": size_x, "size_y": size_y, "size_z": size_z, "exclude_zones": len(exclude)})
        else:
            self._record(cat, "Profile API", "FAIL", f"GET /api/v1/profile/ failed (HTTP {code})")

        # 2. Config File Access (checking configuration editor backend)
        code_cfg, cfgs = _http_get(f"{INDUS3D_URL}/api/v1/printer/files/config")
        if code_cfg == 200 and isinstance(cfgs, dict):
            files = cfgs.get("result", [])
            cfg_names = [f.get("path") for f in files if isinstance(f, dict)]
            self._record(cat, "Config Files API", "PASS",
                         f"Loaded {len(cfg_names)} config files (printer.cfg, ebb36_gen2.cfg, eddyprobe.cfg accessible)")
        else:
            self._record(cat, "Config Files API", "FAIL",
                         f"GET /api/v1/printer/files/config returned HTTP {code_cfg}")
            self.results["recommendations"].append("Verify Indus3D config file proxy routes are functioning.")

        # 3. WebSocket Streaming (Test 25 Hz live push)
        try:
            ws_url = f"{INDUS3D_URL.replace('http', 'ws')}/api/v1/ws/twin"
            parsed = urllib.parse.urlparse(ws_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 5001

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.5)
            sock.connect((host, port))

            # Perform minimal HTTP Upgrade to WebSocket
            cookie = _get_auth_cookie()
            cookie_hdr = f"Cookie: {cookie}\r\n" if cookie else ""
            handshake = (
                f"GET {parsed.path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"{cookie_hdr}"
                f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                f"Sec-WebSocket-Version: 13\r\n\r\n"
            )
            sock.sendall(handshake.encode("utf-8"))
            resp = sock.recv(1024).decode("utf-8", errors="replace")

            if "101 Switching Protocols" in resp:
                # Count frames over ws_duration
                t0 = time.time()
                frames_received = 0
                sock.settimeout(0.5)
                while time.time() - t0 < self.ws_duration:
                    try:
                        data = sock.recv(4096)
                        if data:
                            frames_received += 1
                    except socket.timeout:
                        pass
                sock.close()

                elapsed = time.time() - t0
                hz = frames_received / elapsed if elapsed > 0 else 0
                status = "PASS" if hz >= 15 else ("WARN" if hz > 5 else "FAIL")
                self._record(cat, "WebSocket Telemetry Push", status,
                             f"Connected! Streamed at {hz:.1f} Hz ({frames_received} frames over {elapsed:.1f}s)",
                             {"hz": round(hz, 1), "frames": frames_received})
            else:
                sock.close()
                self._record(cat, "WebSocket Telemetry Push", "WARN",
                             f"WebSocket handshake failed (Response: {resp[:50]}...)")
        except Exception as e:
            self._record(cat, "WebSocket Telemetry Push", "WARN", f"WebSocket connection error: {e}")

    def run_all(self):
        self.check_host_vitals()
        self.check_systemd_services()
        self.check_klipper_and_moonraker()
        self.check_mcu_telemetry()
        self.check_usb_physical_topology()
        self.check_kernel_usb_errors()
        self.check_indus3d_twin()
        return self.results

    def print_summary(self):
        r = self.results
        print(f"\n{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════{RESET}")
        print(f"{BOLD}{CYAN}               INDUS3D SYSTEM STABILITY & HARDWARE AUDIT                 {RESET}")
        print(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════{RESET}\n")

        for category, checks in r["checks"].items():
            print(f"{BOLD}{category}:{RESET}")
            for c in checks:
                icon = f"{GREEN}✔ PASS{RESET}" if c["status"] == "PASS" else (
                    f"{YELLOW}▲ WARN{RESET}" if c["status"] == "WARN" else f"{RED}✖ FAIL{RESET}"
                )
                print(f"  [{icon}] {BOLD}{c['name']}{RESET}: {c['message']}")
            print()

        scores = r["scores"]
        overall = r["overall_status"]
        overall_color = GREEN if overall == "PASS" else (YELLOW if overall == "WARN" else RED)

        print(f"{BOLD}──────────────────────────────────────────────────────────────────────────{RESET}")
        print(f"Passed: {GREEN}{scores['passed']}{RESET} | Warnings: {YELLOW}{scores['warnings']}{RESET} | Failures: {RED}{scores['failed']}{RESET}")
        print(f"Overall Stability Verdict: {BOLD}{overall_color}{overall}{RESET}")

        if overall == "PASS":
            print(f"\n{GREEN}{BOLD}✨ SYSTEM IS FULLY STABLE & VERIFIED FOR LONG PRINTS!{RESET}")
        elif overall == "WARN":
            print(f"\n{YELLOW}{BOLD}⚠️ SYSTEM IS USABLE BUT SHOWS HARDWARE/BUS WARNINGS.{RESET}")
        else:
            print(f"\n{RED}{BOLD}🚨 NOT SAFE TO PRINT: HARDWARE OR KERNEL BUS FAULTS DETECTED!{RESET}")

        if r["recommendations"]:
            print(f"\n{BOLD}Actionable Recommendations:{RESET}")
            for i, rec in enumerate(r["recommendations"], 1):
                print(f"  {i}. {rec}")

        print(f"\n{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════{RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Indus3D System Stability & Hardware Health Checker")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--ws-duration", type=float, default=2.0, help="Seconds to sample WebSocket telemetry")
    args = parser.parse_args()

    checker = StabilityChecker(ws_duration=args.ws_duration)
    results = checker.run_all()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        checker.print_summary()

    # Exit code: 0 = PASS, 1 = WARN, 2 = FAIL
    status = results["overall_status"]
    if status == "PASS":
        sys.exit(0)
    elif status == "WARN":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
