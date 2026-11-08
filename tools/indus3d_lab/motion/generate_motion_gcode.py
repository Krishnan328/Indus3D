#!/usr/bin/env python3
"""Create review-only, travel-only motion test G-code.

The generator is intentionally disconnected from printers and refuses to
write a normal ``.gcode`` filename unless the operator supplies an explicit
override.  Review the resulting file and run validate_gcode.py before any
manual upload to a printer.
"""

from __future__ import annotations

import argparse
from pathlib import Path


MAX_FEEDRATE_MM_MIN = 6_000


def positive(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", choices=("rectangle", "serpentine"), required=True)
    parser.add_argument("--x-max", type=positive, required=True, help="Verified Klipper X position_max in mm")
    parser.add_argument("--y-max", type=positive, required=True, help="Verified Klipper Y position_max in mm")
    parser.add_argument("--z-max", type=positive, required=True, help="Verified Klipper Z position_max in mm")
    parser.add_argument("--margin", type=positive, required=True, help="Inset from every XY limit in mm")
    parser.add_argument("--z-clearance", type=positive, required=True, help="Safe travel/test height in mm")
    parser.add_argument("--feedrate", type=positive, required=True, help="Travel speed in mm/min (max 6000)")
    parser.add_argument("--passes", type=int, default=1, help="1–10 perimeter passes or serpentine repetitions")
    parser.add_argument("--line-spacing", type=positive, default=25, help="Serpentine line spacing in mm")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-gcode-extension", action="store_true", help="Allow .gcode output after manual review")
    return parser


def validate_inputs(args: argparse.Namespace) -> None:
    if args.passes < 1 or args.passes > 10:
        raise ValueError("--passes must be between 1 and 10")
    if args.feedrate > MAX_FEEDRATE_MM_MIN:
        raise ValueError(f"--feedrate must not exceed {MAX_FEEDRATE_MM_MIN} mm/min")
    if args.z_clearance >= args.z_max:
        raise ValueError("--z-clearance must be below --z-max")
    if 2 * args.margin >= args.x_max or 2 * args.margin >= args.y_max:
        raise ValueError("--margin leaves no usable XY area")
    if args.output.suffix.lower() == ".gcode" and not args.allow_gcode_extension:
        raise ValueError("Refusing .gcode output; use .gcode.review or explicitly pass --allow-gcode-extension")


def move(x: float, y: float, z: float, feedrate: float) -> str:
    return f"G1 X{x:.3f} Y{y:.3f} Z{z:.3f} F{feedrate:.0f}"


def header(args: argparse.Namespace) -> list[str]:
    return [
        "; INDUS3D REVIEW-ONLY MOTION TEST",
        "; No command in this file was sent by Indus3D. Upload/run manually only after the checklist.",
        "; No homing, heating, extrusion, probing, or firmware-setting commands are included.",
        f"; Verified-envelope input: X=0..{args.x_max:.3f}, Y=0..{args.y_max:.3f}, Z=0..{args.z_max:.3f} mm",
        f"; Safety margin: {args.margin:.3f} mm; test Z: {args.z_clearance:.3f} mm; feedrate: {args.feedrate:.0f} mm/min",
        "; REQUIREMENTS: printer homed manually, bed clear, no active print, emergency stop accessible.",
        "M400 ; wait for any previously queued motion",
        "G90 ; absolute coordinates",
    ]


def rectangle(args: argparse.Namespace) -> list[str]:
    x0, x1 = args.margin, args.x_max - args.margin
    y0, y1 = args.margin, args.y_max - args.margin
    lines = ["; Pattern: conservative XY perimeter"]
    lines.append(move(x0, y0, args.z_clearance, args.feedrate))
    for _ in range(args.passes):
        for x, y in ((x1, y0), (x1, y1), (x0, y1), (x0, y0)):
            lines.append(move(x, y, args.z_clearance, args.feedrate))
    return lines


def serpentine(args: argparse.Namespace) -> list[str]:
    x0, x1 = args.margin, args.x_max - args.margin
    y0, y1 = args.margin, args.y_max - args.margin
    rows: list[float] = []
    y = y0
    while y < y1:
        rows.append(y)
        y += args.line_spacing
    if not rows or rows[-1] != y1:
        rows.append(y1)

    lines = ["; Pattern: conservative serpentine X traversals"]
    for _ in range(args.passes):
        at_left = True
        for y in rows:
            lines.append(move(x0 if at_left else x1, y, args.z_clearance, args.feedrate))
            lines.append(move(x1 if at_left else x0, y, args.z_clearance, args.feedrate))
            at_left = not at_left
    return lines


def build_program(args: argparse.Namespace) -> str:
    lines = header(args)
    lines.extend(rectangle(args) if args.pattern == "rectangle" else serpentine(args))
    park_x, park_y = args.x_max / 2, args.y_max / 2
    lines.extend([
        "; Park only within supplied machine envelope",
        move(park_x, park_y, args.z_clearance, args.feedrate),
        "M400 ; confirm all planned motion has completed",
        "; END REVIEW-ONLY MOTION TEST",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    args = build_parser().parse_args()
    try:
        validate_inputs(args)
    except ValueError as error:
        raise SystemExit(f"Safety check failed: {error}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_program(args), encoding="utf-8")
    print(f"Wrote review-only program: {args.output}")
    print("Next: validate it, inspect it, then decide manually whether to upload it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
