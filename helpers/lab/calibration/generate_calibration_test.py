#!/usr/bin/env python3
"""Generate review-only calibration G-code; this script never contacts a printer."""

from __future__ import annotations

import argparse
from pathlib import Path

MAX_EXTRUSION_MM = 50.0


def positive(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--test", required=True, choices=("resonance", "thermal", "extrusion", "flow"))
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--axis", choices=("x", "y", "both"), default="both")
    p.add_argument("--heater", choices=("extruder", "heater_bed"), default="extruder")
    p.add_argument("--target", type=positive, default=200.0)
    p.add_argument("--hold-seconds", type=int, default=60)
    p.add_argument("--length", type=positive, default=50.0)
    p.add_argument("--feedrate", type=positive, default=120.0)
    p.add_argument("--minimum-temp", type=positive, default=170.0)
    p.add_argument("--x-max", type=positive)
    p.add_argument("--y-max", type=positive)
    p.add_argument("--z-max", type=positive)
    p.add_argument("--margin", type=positive, default=25.0)
    p.add_argument("--z-height", type=positive, default=0.30)
    p.add_argument("--side", type=positive, default=20.0)
    p.add_argument("--extrusion-per-mm", type=positive, default=0.04)
    return p


def validate(args: argparse.Namespace) -> None:
    if args.output.suffix.lower() == ".gcode" or not args.output.name.endswith(".review"):
        raise ValueError("output must end in .review; this tool never writes runnable G-code")
    if not 10 <= args.hold_seconds <= 300:
        raise ValueError("--hold-seconds must be between 10 and 300")
    if args.length > MAX_EXTRUSION_MM or args.feedrate > 600 or args.minimum_temp > 280:
        raise ValueError("extrusion limits exceeded (50 mm, 600 mm/min, 280 °C)")
    if args.test == "thermal":
        low, high = ((150, 280) if args.heater == "extruder" else (30, 110))
        if not low <= args.target <= high:
            raise ValueError(f"--target for {args.heater} must be {low}..{high} °C")
    if args.test == "flow":
        if not all((args.x_max, args.y_max, args.z_max)):
            raise ValueError("flow test requires --x-max, --y-max, and --z-max from verified Klipper limits")
        if args.z_height >= args.z_max or 2 * args.margin + args.side > min(args.x_max, args.y_max):
            raise ValueError("flow sample does not fit inside the verified envelope")
        if 4 * args.side * args.extrusion_per_mm > MAX_EXTRUSION_MM:
            raise ValueError("flow sample exceeds conservative extrusion limit")


def header(test: str) -> list[str]:
    return [
        "; INDUS3D REVIEW-ONLY CALIBRATION TEST", f"; Test: {test}",
        "; Generated offline. Indus3D did not upload, queue, or execute this program.",
        "; REQUIREMENTS: ready printer, no active job, physical preflight complete, emergency stop accessible.",
        "; REVIEW REQUIRED: validate this artifact and create a manual approval record before any upload.", "M400",
    ]


def program(args: argparse.Namespace) -> list[str]:
    if args.test == "resonance":
        axes = ("X", "Y") if args.axis == "both" else (args.axis.upper(),)
        return [f"TEST_RESONANCES AXIS={axis} OUTPUT=raw_data" for axis in axes] + ["M400"]
    if args.test == "thermal":
        sensor = "extruder" if args.heater == "extruder" else "heater_bed"
        return [f"SET_HEATER_TEMPERATURE HEATER={args.heater} TARGET={args.target:.1f}",
                f"TEMPERATURE_WAIT SENSOR={sensor} MINIMUM={args.target - 3:.1f} MAXIMUM={args.target + 3:.1f}",
                f"G4 P{args.hold_seconds * 1000}", "TURN_OFF_HEATERS", "M400"]
    if args.test == "extrusion":
        return [f"TEMPERATURE_WAIT SENSOR=extruder MINIMUM={args.minimum_temp:.1f}",
                "; Manually mark filament first. This program never sets a heater target.", "M83",
                f"G1 E{args.length:.3f} F{args.feedrate:.1f}", "M82", "M400"]
    x0, y0, z, side = args.margin, args.margin, args.z_height, args.side
    x1, y1, e = x0 + side, y0 + side, side * args.extrusion_per_mm
    return [f"TEMPERATURE_WAIT SENSOR=extruder MINIMUM={args.minimum_temp:.1f}",
            "; Manually preheat, home, and confirm the bed is clear. This program never sets targets or homes.",
            "G90", "M83", f"G1 X{x0:.3f} Y{y0:.3f} Z{z:.3f} F{args.feedrate:.1f}",
            f"G1 X{x1:.3f} Y{y0:.3f} E{e:.4f} F{args.feedrate:.1f}",
            f"G1 X{x1:.3f} Y{y1:.3f} E{e:.4f} F{args.feedrate:.1f}",
            f"G1 X{x0:.3f} Y{y1:.3f} E{e:.4f} F{args.feedrate:.1f}",
            f"G1 X{x0:.3f} Y{y0:.3f} E{e:.4f} F{args.feedrate:.1f}", "M82", "M400"]


def main() -> int:
    args = parser().parse_args()
    try:
        validate(args)
    except ValueError as exc:
        raise SystemExit(f"Safety check failed: {exc}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(header(args.test) + program(args) + ["; END REVIEW-ONLY CALIBRATION TEST", ""]), encoding="utf-8")
    print(f"Wrote review-only calibration program: {args.output}")
    print("Next: validate, inspect, record approval, then decide manually whether to upload/run it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
