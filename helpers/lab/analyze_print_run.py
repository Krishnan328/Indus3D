#!/usr/bin/env python3
"""Summarize a GET-only Indus3D Lab telemetry capture with transparent math."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "max": None, "mean": None, "stdev": None}
    return {"min": min(values), "max": max(values), "mean": mean(values), "stdev": statistics.stdev(values) if len(values) > 1 else 0.0}


def numbers(records: Iterable[dict], key: str) -> list[float]:
    values = []
    for record in records:
        value = record.get("telemetry", {}).get(key)
        if isinstance(value, (int, float)) and math.isfinite(value):
            values.append(float(value))
    return values


def calculate(records: list[dict]) -> dict:
    observed_path_mm = 0.0
    observed_velocity: list[float] = []
    previous = None
    for record in records:
        data = record.get("telemetry", {})
        point = (record.get("monotonic_seconds"), data.get("live_x"), data.get("live_y"), data.get("live_z"))
        if previous and all(isinstance(v, (int, float)) for v in point + previous):
            dt = point[0] - previous[0]
            distance = math.dist(point[1:], previous[1:])
            if dt > 0:
                observed_path_mm += distance
                observed_velocity.append(distance / dt)
        previous = point
    times = [record.get("monotonic_seconds") for record in records if isinstance(record.get("monotonic_seconds"), (int, float))]
    states = Counter(record.get("telemetry", {}).get("state", "unknown") for record in records)
    errors = sum(1 for record in records if record.get("errors"))
    return {
        "schema": "indus3d-lab-report-v1",
        "samples": len(records),
        "duration_seconds": (max(times) - min(times)) if len(times) > 1 else 0.0,
        "failed_samples": errors,
        "states": dict(states),
        "temperatures_c": {"extruder": stats(numbers(records, "extTemp")), "bed": stats(numbers(records, "bedTemp"))},
        "controls_percent": {"speed_factor": stats(numbers(records, "speed_factor")), "flow_factor": stats(numbers(records, "flow_factor"))},
        "kinematics": {"observed_path_mm": observed_path_mm, "observed_velocity_mm_s": stats(observed_velocity)},
    }


def markdown(report: dict, source: Path) -> str:
    def fmt(value: object) -> str:
        return "—" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)
    lines = ["# Indus3D Lab print-run report", "", f"Source: `{source}`", "", "## Capture", "", f"- Samples: {report['samples']}", f"- Duration: {fmt(report['duration_seconds'])} s", f"- Failed samples: {report['failed_samples']}", f"- States: {', '.join(f'{name}={count}' for name, count in report['states'].items()) or '—'}", "", "## Measurements", "", "| Metric | Min | Mean | Max | Std. dev. |", "| --- | ---: | ---: | ---: | ---: |"]
    for group, label in (("temperatures_c", "Extruder °C"), ("temperatures_c", "Bed °C"), ("controls_percent", "Speed factor %"), ("controls_percent", "Flow factor %"), ("kinematics", "Observed velocity mm/s")):
        key = {"Extruder °C": "extruder", "Bed °C": "bed", "Speed factor %": "speed_factor", "Flow factor %": "flow_factor", "Observed velocity mm/s": "observed_velocity_mm_s"}[label]
        item = report[group][key]
        lines.append(f"| {label} | {fmt(item['min'])} | {fmt(item['mean'])} | {fmt(item['max'])} | {fmt(item['stdev'])} |")
    lines.extend(["", "## Derived motion math", "", f"- Observed toolhead path: **{fmt(report['kinematics']['observed_path_mm'])} mm**", "- Velocity is calculated from consecutive telemetry points: `distance_3D / elapsed_time`.", "- This is an observation of reported live coordinates, not a safety validation or a substitute for Klipper's motion limits.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for number, line in enumerate(args.capture.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                parser.error(f"invalid JSON on line {number}: {exc}")
    report = calculate(records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "report.md").write_text(markdown(report, args.capture), encoding="utf-8")
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
