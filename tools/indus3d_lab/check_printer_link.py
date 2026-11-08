#!/usr/bin/env python3
"""Read-only Klipper MCU connection diagnostic.

Reads the active printer configuration and compares each configured serial MCU
path with devices currently exposed by Linux. It never restarts Klipper or
sends G-code; use it after reconnecting a printer controller or USB hub.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def configured_serial_paths(config: Path) -> list[tuple[str, str]]:
    """Return ``(mcu section, serial path)`` pairs from a Klipper config."""
    current = ""
    result: list[tuple[str, str]] = []
    for raw in config.read_text(encoding="utf-8", errors="replace").splitlines():
        section = re.match(r"^\s*\[([^]]+)\]", raw)
        if section:
            current = section.group(1).strip()
            continue
        serial = re.match(r"^\s*serial\s*:\s*(\S+)", raw)
        if serial and (current == "mcu" or current.startswith("mcu ")):
            result.append((current, serial.group(1)))
    return result


def service_state() -> str:
    try:
        return subprocess.check_output(
            ["systemctl", "is-active", "klipper"], text=True, stderr=subprocess.DEVNULL, timeout=3
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def present_serial_devices() -> list[str]:
    paths: list[Path] = []
    for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*", "/dev/serial/by-id/*", "/dev/serial/by-path/*"):
        paths.extend(Path("/").glob(pattern.removeprefix("/")))
    return sorted({str(path) for path in paths})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--printer-config", type=Path, default=Path("/var/lib/moonraker/config/printer.cfg"),
        help="active Klipper printer.cfg path",
    )
    args = parser.parse_args()
    if not args.printer_config.is_file():
        print(f"ERROR: printer configuration not found: {args.printer_config}")
        return 2

    configured = configured_serial_paths(args.printer_config)
    print(f"klipper_service={service_state()}")
    if not configured:
        print("No serial MCU paths found; inspect CAN or include configuration manually.")
        return 1

    missing = False
    for section, raw_path in configured:
        path = Path(raw_path)
        exists = path.exists()
        resolved = str(path.resolve()) if exists else "missing"
        print(f"{section}: configured={raw_path} present={str(exists).lower()} resolved={resolved}")
        missing = missing or not exists

    devices = present_serial_devices()
    print("detected_serial_devices=" + (", ".join(devices) if devices else "none"))
    if missing:
        print("ACTION: restore controller power/USB/hub connection, then rerun this tool. Do not issue FIRMWARE_RESTART until every configured MCU path is present.")
        return 1
    print("All configured serial MCU paths are present. Review Klipper logs, then decide manually whether a firmware restart is appropriate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
