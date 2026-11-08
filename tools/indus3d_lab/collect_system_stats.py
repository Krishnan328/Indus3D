#!/usr/bin/env python3
"""Capture a read-only resource snapshot for an Indus3D host.

No printer APIs are contacted.  The optional systemd queries only call
``systemctl show`` and are useful on NixOS/Linux; unsupported hosts still get
portable CPU, memory, disk, and process information.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _run(*args: str) -> str | None:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=4).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    raw = _read("/proc/meminfo")
    if not raw:
        return values
    for line in raw.splitlines():
        key, value = line.split(":", 1)
        amount = value.strip().split()[0]
        if amount.isdigit():
            values[key] = int(amount) * 1024
    return values


def _processes() -> list[dict[str, Any]]:
    raw = _run("ps", "-eo", "pid,ppid,%cpu,%mem,rss,etime,comm,args", "--sort=-%cpu")
    if not raw:
        return []
    records: list[dict[str, Any]] = []
    for line in raw.splitlines()[1:]:
        # ``args`` is the final, free-form column. Limit the split before it
        # so spaces in a command line do not shift the process metadata.
        fields = line.split(None, 7)
        if len(fields) != 8:
            continue
        pid, ppid, cpu, mem, rss, elapsed, command, args = fields
        records.append({
            "pid": int(pid), "ppid": int(ppid), "cpu_percent": float(cpu),
            "memory_percent": float(mem), "rss_bytes": int(rss) * 1024,
            "elapsed": elapsed, "command": command, "args": args,
        })
    return records


def _service(name: str) -> dict[str, Any]:
    fields = [
        "ActiveState", "SubState", "MainPID", "CPUUsageNSec", "MemoryCurrent",
        "TasksCurrent", "NRestarts", "User", "DynamicUser",
    ]
    raw = _run("systemctl", "show", name, "--no-pager", *sum((["-p", key] for key in fields), []))
    data: dict[str, Any] = {"name": name, "available": raw is not None}
    if raw is None:
        return data
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    for key in ("MainPID", "CPUUsageNSec", "MemoryCurrent", "TasksCurrent", "NRestarts"):
        if data.get(key, "").isdigit():
            data[key] = int(data[key])
    if isinstance(data.get("CPUUsageNSec"), int):
        data["cpu_usage_usec"] = data["CPUUsageNSec"] // 1_000
    if isinstance(data.get("MemoryCurrent"), int):
        data["memory_current_bytes"] = data["MemoryCurrent"]
    return data


def snapshot(services: list[str]) -> dict[str, Any]:
    mem = _meminfo()
    usage = shutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
    return {
        "schema": "indus3d-lab-system-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": {"hostname": platform.node(), "platform": platform.platform(), "cpu_count": os.cpu_count()},
        "load_average": {"1m": load[0], "5m": load[1], "15m": load[2]},
        "memory_bytes": {
            "total": mem.get("MemTotal"), "available": mem.get("MemAvailable"),
            "cached": mem.get("Cached"), "swap_total": mem.get("SwapTotal"),
            "swap_free": mem.get("SwapFree"),
        },
        "root_disk_bytes": {"total": usage.total, "used": usage.used, "free": usage.free},
        "services": {name: _service(name) for name in services},
        "top_processes": _processes()[:25],
        "monotonic_seconds": time.monotonic(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", action="append", default=[], help="systemd service to include (repeatable)")
    parser.add_argument("--output", type=Path, help="write JSON to this path; stdout if omitted")
    args = parser.parse_args()
    payload = snapshot(args.service)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(args.output)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
