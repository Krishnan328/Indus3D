#!/usr/bin/env python3
"""Validate the restricted motion-test G-code produced by this folder.

This is a static check, not a proof of safety.  It rejects commands outside
the small command subset used by the generator and checks absolute XYZ moves
against the supplied envelope and margin.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


FORBIDDEN = re.compile(r"\b(?:G28|M104|M109|M140|M190|M112|M500|M501|G92|G10|G11|PID_CALIBRATE|SHAPER_CALIBRATE|TEST_RESONANCES)\b", re.I)
MOVE = re.compile(r"^(?:G0|G1)\s+(.*)$", re.I)
COORD = re.compile(r"\b([XYZEF])\s*(-?\d+(?:\.\d+)?)\b", re.I)
ALLOWED = ("M400", "G90", "G0", "G1")


def positive(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("file", type=Path)
    p.add_argument("--x-max", type=positive, required=True)
    p.add_argument("--y-max", type=positive, required=True)
    p.add_argument("--z-max", type=positive, required=True)
    p.add_argument("--margin", type=positive, required=True)
    return p


def main() -> int:
    args = parser().parse_args()
    if 2 * args.margin >= args.x_max or 2 * args.margin >= args.y_max:
        raise SystemExit("Invalid envelope: margin leaves no usable XY area")
    errors: list[str] = []
    seen_g90 = False
    for line_number, raw in enumerate(args.file.read_text(encoding="utf-8").splitlines(), 1):
        code = raw.partition(";")[0].strip().upper()
        if not code:
            continue
        if FORBIDDEN.search(code):
            errors.append(f"line {line_number}: prohibited command: {code}")
            continue
        if not code.startswith(ALLOWED):
            errors.append(f"line {line_number}: unsupported command: {code}")
            continue
        if code == "G90":
            seen_g90 = True
            continue
        match = MOVE.match(code)
        if not match:
            continue
        if not seen_g90:
            errors.append(f"line {line_number}: move precedes absolute-coordinate G90")
        terms = {axis.upper(): float(value) for axis, value in COORD.findall(match.group(1))}
        if "E" in terms:
            errors.append(f"line {line_number}: extrusion term is not allowed")
        checks = {
            "X": (args.margin, args.x_max - args.margin),
            "Y": (args.margin, args.y_max - args.margin),
            "Z": (0.0, args.z_max),
        }
        for axis, (low, high) in checks.items():
            if axis in terms and not low <= terms[axis] <= high:
                errors.append(f"line {line_number}: {axis}{terms[axis]} outside safe range {low}..{high}")
    if errors:
        print("VALIDATION FAILED")
        print("\n".join(errors))
        return 1
    print("VALIDATION PASSED: restricted commands and supplied coordinate envelope look consistent.")
    print("Still perform the physical preflight checklist before any manual upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
