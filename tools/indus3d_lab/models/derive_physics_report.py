#!/usr/bin/env python3
"""Derive transparent, offline motion, thermal, energy and vibration checks.

Input is the JSONL produced by ../capture_print_telemetry.py.  No network or
printer interfaces are used by this program.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def finite(value: Any) -> Optional[float]:
    """Return a finite number, excluding booleans and malformed values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def summary(values: Iterable[float]) -> Dict[str, Optional[float]]:
    data = list(values)
    if not data:
        return {"count": 0, "min": None, "mean": None, "max": None, "stdev": None}
    return {
        "count": len(data),
        "min": min(data),
        "mean": statistics.fmean(data),
        "max": max(data),
        "stdev": statistics.stdev(data) if len(data) > 1 else 0.0,
    }


def telemetry(record: Dict[str, Any]) -> Dict[str, Any]:
    data = record.get("telemetry")
    return data if isinstance(data, dict) else {}


def elapsed(record: Dict[str, Any]) -> Optional[float]:
    return finite(record.get("monotonic_seconds"))


def movement_and_energy(records: List[Dict[str, Any]], mass_kg: float) -> Dict[str, Any]:
    """Calculate finite-difference kinematics from reported live positions."""
    path_mm = 0.0
    velocities: List[float] = []
    accelerations: List[float] = []
    energies_j: List[float] = []
    previous: Optional[Tuple[float, float, float, float]] = None
    previous_velocity: Optional[Tuple[float, float]] = None

    for record in records:
        state = telemetry(record)
        point = (elapsed(record), finite(state.get("live_x")), finite(state.get("live_y")), finite(state.get("live_z")))
        if any(value is None for value in point):
            continue
        now, x, y, z = point  # type: ignore[misc]
        if previous is not None:
            dt = now - previous[0]
            if dt > 0:
                distance = math.dist((x, y, z), previous[1:])
                velocity = distance / dt
                path_mm += distance
                velocities.append(velocity)
                energies_j.append(0.5 * mass_kg * (velocity / 1000.0) ** 2)
                if previous_velocity is not None:
                    dv_dt = (velocity - previous_velocity[1]) / (now - previous_velocity[0])
                    accelerations.append(dv_dt)
                previous_velocity = (now, velocity)
        previous = (now, x, y, z)

    return {
        "toolhead_mass_kg": mass_kg,
        "observed_path_mm": path_mm,
        "velocity_mm_s": summary(velocities),
        "acceleration_mm_s2": summary(accelerations),
        "translational_kinetic_energy_j": summary(energies_j),
        "formulae": {
            "velocity": "distance_3d_mm / elapsed_seconds",
            "acceleration": "(velocity_i - velocity_i-1) / elapsed_seconds",
            "kinetic_energy": "0.5 * toolhead_mass_kg * (velocity_mm_s / 1000)^2",
        },
    }


def temperature_and_energy(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    temperatures: Dict[str, List[float]] = {"extruder": [], "bed": []}
    temperature_slopes: Dict[str, List[float]] = {"extruder": [], "bed": []}
    previous: Dict[str, Tuple[float, float]] = {}
    power_points: List[Tuple[float, float]] = []

    for record in records:
        now = elapsed(record)
        if now is None:
            continue
        state = telemetry(record)
        for name, key in (("extruder", "extTemp"), ("bed", "bedTemp")):
            value = finite(state.get(key))
            if value is None:
                continue
            temperatures[name].append(value)
            if name in previous and now > previous[name][0]:
                temperature_slopes[name].append((value - previous[name][1]) / (now - previous[name][0]))
            previous[name] = (now, value)
        power = state.get("power")
        if isinstance(power, dict):
            watts = finite(power.get("power_w"))
            if watts is not None and watts >= 0:
                power_points.append((now, watts))

    watt_seconds = 0.0
    intervals = 0
    for (t0, p0), (t1, p1) in zip(power_points, power_points[1:]):
        if t1 > t0:
            watt_seconds += ((p0 + p1) / 2.0) * (t1 - t0)
            intervals += 1
    return {
        "temperatures_c": {name: summary(values) for name, values in temperatures.items()},
        "temperature_slope_c_per_s": {name: summary(values) for name, values in temperature_slopes.items()},
        "power_w": summary(power for _, power in power_points),
        "energy_wh": watt_seconds / 3600.0 if intervals else None,
        "energy_intervals": intervals,
        "formulae": {
            "temperature_slope": "(temperature_i - temperature_i-1) / elapsed_seconds",
            "energy": "sum(((power_i + power_i+1) / 2) * elapsed_seconds) / 3600",
        },
    }


def vibration(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Dict[str, Any]] = {}
    for axis in ("x", "y", "z"):
        measurements: Dict[str, List[float]] = {"rms": [], "magnitude": [], "peak_hz": [], "kurtosis": []}
        for record in records:
            vib = telemetry(record).get("vibration")
            axis_data = vib.get(axis) if isinstance(vib, dict) else None
            if not isinstance(axis_data, dict):
                continue
            for name in measurements:
                value = finite(axis_data.get(name))
                if value is not None:
                    measurements[name].append(value)
        result[axis] = {name: summary(values) for name, values in measurements.items()}
    return {
        "axes": result,
        "interpretation": "Peak frequency and kurtosis are summaries of the existing DSP output; they are not a substitute for Klipper resonance calibration.",
    }


def gcode_time_estimate(path: Path) -> Dict[str, Any]:
    """Estimate linear-move time from standard G0/G1 modal G-code only."""
    position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    absolute = True
    feed_mm_min: Optional[float] = None
    moves = 0
    path_mm = 0.0
    seconds = 0.0

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split(";", 1)[0].strip().upper()
        if not line:
            continue
        words = line.split()
        command = words[0]
        if command == "G90":
            absolute = True
            continue
        if command == "G91":
            absolute = False
            continue
        if command not in {"G0", "G00", "G1", "G01"}:
            continue
        target = dict(position)
        for word in words[1:]:
            if len(word) < 2:
                continue
            letter = word[0]
            try:
                value = float(word[1:])
            except ValueError:
                continue
            if letter == "F" and value > 0:
                feed_mm_min = value
            elif letter in target:
                target[letter] = value if absolute else target[letter] + value
        distance = math.dist(tuple(position.values()), tuple(target.values()))
        if distance > 0 and feed_mm_min:
            path_mm += distance
            seconds += distance / (feed_mm_min / 60.0)
            moves += 1
        position = target
    return {
        "source": str(path),
        "linear_moves_counted": moves,
        "linear_path_mm": path_mm,
        "lower_bound_motion_seconds": seconds,
        "formula": "sum(distance_3d_mm / (feedrate_mm_min / 60)) for G0/G1 moves",
        "limitations": "Excludes acceleration, junction limits, dwell, heating, homing, probing, pressure advance, firmware look-ahead and non-linear kinematics.",
    }


def build_report(records: List[Dict[str, Any]], mass_kg: float, gcode: Optional[Path]) -> Dict[str, Any]:
    times = [value for value in (elapsed(record) for record in records) if value is not None]
    report: Dict[str, Any] = {
        "schema": "indus3d-lab-physics-v1",
        "capture": {
            "samples": len(records),
            "duration_seconds": max(times) - min(times) if len(times) > 1 else 0.0,
            "valid_timestamps": len(times),
        },
        "motion": movement_and_energy(records, mass_kg),
        "thermal_and_energy": temperature_and_energy(records),
        "vibration": vibration(records),
        "assumptions": [
            "All calculations are offline and passive.",
            "Telemetry is sampled data; values between samples are not observed.",
            "The entered toolhead mass is an estimate for kinetic-energy comparison only.",
        ],
    }
    if gcode is not None:
        report["gcode_time_estimate"] = gcode_time_estimate(gcode)
    return report


def markdown(report: Dict[str, Any], source: Path) -> str:
    motion = report["motion"]
    thermal = report["thermal_and_energy"]
    gcode = report.get("gcode_time_estimate")
    def fmt(value: Any) -> str:
        return "—" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)
    lines = [
        "# Indus3D Lab physics report",
        "",
        f"Source: `{source}`",
        "",
        "## Motion",
        "",
        f"- Observed path: **{fmt(motion['observed_path_mm'])} mm**",
        f"- Mean / peak observed velocity: **{fmt(motion['velocity_mm_s']['mean'])} / {fmt(motion['velocity_mm_s']['max'])} mm/s**",
        f"- Peak estimated translational energy: **{fmt(motion['translational_kinetic_energy_j']['max'])} J** (mass assumption: {fmt(motion['toolhead_mass_kg'])} kg)",
        "",
        "## Thermal and energy",
        "",
        f"- Extruder mean temperature: **{fmt(thermal['temperatures_c']['extruder']['mean'])} °C**",
        f"- Bed mean temperature: **{fmt(thermal['temperatures_c']['bed']['mean'])} °C**",
        f"- Integrated energy: **{fmt(thermal['energy_wh'])} Wh** across {thermal['energy_intervals']} valid power intervals",
    ]
    if gcode:
        lines.extend([
            "",
            "## G-code lower-bound motion time",
            "",
            f"- Counted moves: {gcode['linear_moves_counted']}",
            f"- Estimated linear path: {fmt(gcode['linear_path_mm'])} mm",
            f"- Lower-bound movement time: **{fmt(gcode['lower_bound_motion_seconds'])} s**",
            f"- Limitation: {gcode['limitations']}",
        ])
    lines.extend(["", "## Verification", "", "Compare this report with the captured wall-clock duration, the finished part, and Klipper/Moonraker history. Do not treat estimates as permission to exceed configured motion or thermal limits.", ""])
    return "\n".join(lines)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON on line {}: {}".format(number, exc)) from exc
        if isinstance(item, dict):
            records.append(item)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="JSONL from capture_print_telemetry.py")
    parser.add_argument("--gcode", type=Path, help="Optional G-code file for a lower-bound linear-motion estimate")
    parser.add_argument("--toolhead-mass-kg", type=float, default=0.40, help="Mass used only for kinetic-energy math (default: 0.40)")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.toolhead_mass_kg <= 0:
        parser.error("--toolhead-mass-kg must be positive")
    if args.gcode and not args.gcode.is_file():
        parser.error("--gcode does not exist: {}".format(args.gcode))
    try:
        records = read_jsonl(args.capture)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    report = build_report(records, args.toolhead_mass_kg, args.gcode)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "physics-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "physics-report.md").write_text(markdown(report, args.capture), encoding="utf-8")
    print(args.output_dir / "physics-report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
