#!/usr/bin/env python3
"""Summarize a passive observation database, including telemetry blind spots."""

import argparse
import json
import sqlite3
from pathlib import Path


def summarize(path):
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        records = [json.loads(row[0]) for row in conn.execute("SELECT payload_json FROM telemetry ORDER BY line_number")]
        telemetry = [row.get("telemetry", {}) for row in records]
        services = {}
        for name, in conn.execute("SELECT DISTINCT service FROM resources"):
            points = [(timestamp, json.loads(raw)) for timestamp, raw in conn.execute(
                "SELECT monotonic_seconds,payload_json FROM resources WHERE service=? ORDER BY id", (name,))]
            first, last = points[0], points[-1]
            elapsed = last[0] - first[0]
            before, after = first[1].get("CPUUsageNSec"), last[1].get("CPUUsageNSec")
            stable = first[1].get("MainPID") == last[1].get("MainPID")
            services[name] = {
                "window_seconds": elapsed,
                "cpu_percent_one_core": (100 * (after - before) / 1e9 / elapsed
                                         if stable and elapsed > 0 and isinstance(before, int) and isinstance(after, int) and after >= before else None),
                "peak_sampled_memory_bytes": max((p.get("MemoryCurrent", 0) for _, p in points if isinstance(p.get("MemoryCurrent"), int)), default=None),
                "stable_pid": stable,
            }
        warnings = []
        if any(t.get("vibration", {}).get("dsp_online") and not t.get("vibration", {}).get("streaming") for t in telemetry):
            warnings.append("DSP online but accelerometer streaming absent: zero vibration is not a measured clean signal.")
        if any(t.get("power", {}).get("connected") and t.get("power", {}).get("power_w") == 0 and t.get("state", t.get("print_state")) == "printing" for t in telemetry):
            warnings.append("Power sensor reports connected but zero watts during printing: verify wiring, units, and sensor data before estimating energy.")
        def stats(key):
            values = [t[key] for t in telemetry if isinstance(t.get(key), (float, int))]
            return {"min": min(values), "max": max(values), "mean": sum(values) / len(values)} if values else None
        return {
            "samples": len(records), "failed_samples": sum(bool(r.get("errors")) for r in records),
            "first": {key: telemetry[0].get(key) for key in ("state", "filename", "progress", "print_duration")} if telemetry else {},
            "last": {key: telemetry[-1].get(key) for key in ("state", "filename", "progress", "print_duration")} if telemetry else {},
            "temperatures_c": {key: stats(key) for key in ("extTemp", "bedTemp")},
            "services": services, "warnings": warnings,
            "events": [dict(kind=kind, detail=detail) for kind, detail in conn.execute("SELECT kind,detail FROM events ORDER BY id")],
            "limitations": ["Only the tail of this print was observed; this is not a whole-print time or energy measurement.",
                            "nginx accounting is server-side only, not Mainsail browser CPU or a matched feature comparison."],
        }
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.database)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
