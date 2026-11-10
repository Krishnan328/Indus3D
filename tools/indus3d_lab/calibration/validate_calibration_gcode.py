#!/usr/bin/env python3
"""Statically validate an Indus3D review-only calibration artifact."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

FORBIDDEN = re.compile(r"\b(?:G28|M104|M109|M140|M190|M112|M500|M501|G92|G10|G11|PID_CALIBRATE|SHAPER_CALIBRATE|SAVE_CONFIG|SET_GCODE_OFFSET|SET_PRESSURE_ADVANCE|SET_VELOCITY_LIMIT)\b", re.I)
COORD = re.compile(r"\b([XYZEF])\s*(-?\d+(?:\.\d+)?)\b", re.I)
ALLOWED = {
    "resonance": {"M400", "TEST_RESONANCES"},
    "thermal": {"M400", "SET_HEATER_TEMPERATURE", "TEMPERATURE_WAIT", "G4", "TURN_OFF_HEATERS"},
    "extrusion": {"M400", "TEMPERATURE_WAIT", "M83", "M82", "G1"},
    "flow": {"M400", "TEMPERATURE_WAIT", "M83", "M82", "G90", "G1"},
}


def positive(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--x-max", type=positive)
    parser.add_argument("--y-max", type=positive)
    parser.add_argument("--z-max", type=positive)
    parser.add_argument("--margin", type=positive, default=25.0)
    args = parser.parse_args()
    content = args.file.read_text(encoding="utf-8")
    test_match = re.search(r"^; Test: (resonance|thermal|extrusion|flow)$", content, re.M)
    test = test_match.group(1) if test_match else ""
    errors = []
    if not args.file.name.endswith(".review"):
        errors.append("artifact must retain its .review extension until manual approval")
    if "; INDUS3D REVIEW-ONLY CALIBRATION TEST" not in content or not test:
        errors.append("missing Indus3D review marker or supported test type")
    extrusion = 0.0
    for number, raw in enumerate(content.splitlines(), 1):
        code = raw.partition(";")[0].strip().upper()
        if not code:
            continue
        if FORBIDDEN.search(code):
            errors.append(f"line {number}: prohibited command: {code}")
            continue
        command = code.split(maxsplit=1)[0]
        if command not in ALLOWED.get(test, set()):
            errors.append(f"line {number}: command not permitted for {test or 'unknown'} test: {command}")
            continue
        terms = {axis.upper(): float(value) for axis, value in COORD.findall(code)}
        if command == "TEST_RESONANCES" and not re.fullmatch(r"TEST_RESONANCES AXIS=[XY] OUTPUT=RAW_DATA", code):
            errors.append(f"line {number}: resonance command must be exactly an X/Y raw-data capture")
        if command == "SET_HEATER_TEMPERATURE":
            match = re.fullmatch(r"SET_HEATER_TEMPERATURE HEATER=(EXTRUDER|HEATER_BED) TARGET=(\d+(?:\.\d+)?)", code)
            if not match:
                errors.append(f"line {number}: unsupported heater command")
            else:
                target, maximum = float(match.group(2)), (280 if match.group(1) == "EXTRUDER" else 110)
                if target > maximum:
                    errors.append(f"line {number}: thermal target exceeds conservative {maximum} °C limit")
        if command == "G4":
            match = re.fullmatch(r"G4 P(\d+)", code)
            if not match or int(match.group(1)) > 300000:
                errors.append(f"line {number}: dwell must be a bounded P value of 300000 ms or less")
        if command == "G1":
            if test == "extrusion" and any(axis in terms for axis in ("X", "Y", "Z")):
                errors.append(f"line {number}: extrusion-only test may not move X/Y/Z")
            if "E" in terms and terms["E"] <= 0:
                errors.append(f"line {number}: extrusion must be a positive relative amount")
            extrusion += terms.get("E", 0.0)
            if test == "flow":
                if not all((args.x_max, args.y_max, args.z_max)):
                    errors.append("flow validation requires --x-max, --y-max, and --z-max")
                else:
                    for axis, low, high in (("X", args.margin, args.x_max - args.margin), ("Y", args.margin, args.y_max - args.margin), ("Z", 0.0, args.z_max)):
                        if axis in terms and not low <= terms[axis] <= high:
                            errors.append(f"line {number}: {axis}{terms[axis]} outside {low}..{high}")
    if extrusion > 50:
        errors.append(f"relative extrusion total {extrusion:.3f} mm exceeds 50 mm")
    if errors:
        print("VALIDATION FAILED\n" + "\n".join(errors))
        return 1
    print(f"VALIDATION PASSED: restricted {test} program.")
    print("This is not permission to run it. Complete the physical preflight and manual approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
