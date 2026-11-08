# Motion-test G-code lab

This folder is deliberately **offline and review-first**.  Its scripts only
write a local file; they never connect to Moonraker, Klipper, serial devices,
or the Indus3D API.  Generated programs contain travel moves only: no
homing, heating, extrusion, probing, or firmware tuning commands.

## Before any later real-world test

1. Confirm that Klipper is `ready`, no print is active, and the bed is empty.
2. Read the printer's *actual* `position_min` / `position_max` values from its
   active Klipper configuration.  Do not estimate them from the bed size.
3. Generate with an intentionally conservative margin and clearance.
4. Run the validator against the exact resulting file.
5. Open the file in a text editor and in the G-code viewer.  Verify every
   coordinate, feed rate, start point, and park point.
6. Home the printer manually immediately before use, then keep a hand on the
   emergency stop.  Start at the slowest profile and observe the first move.

Do not run a generated file while a part, clips, purge bucket, probe, camera
arm, or loose cable can enter the toolhead path.  These files do not replace
Klipper's bounds checks or a physical safety inspection.

## Generate a review file

The machine envelope is required on every invocation.  The output defaults to
the non-uploadable `.gcode.review` suffix, helping prevent accidental upload.

```bash
python3 generate_motion_gcode.py \
  --pattern rectangle --x-max 220 --y-max 220 --z-max 250 \
  --margin 25 --z-clearance 10 --feedrate 1800 \
  --output /tmp/indus3d-rectangle.gcode.review

python3 validate_gcode.py /tmp/indus3d-rectangle.gcode.review \
  --x-max 220 --y-max 220 --z-max 250 --margin 25
```

`serpentine` makes evenly spaced X traversals at a safe, fixed Z.  `rectangle`
traces the usable perimeter.  Both patterns are useful for checking
coordinates, belt behaviour, and the digital twin's motion trace.  They are
not a substitute for Klipper's native `TEST_RESONANCES` / `SHAPER_CALIBRATE`
workflow when tuning input shapers.

## Deliberately disabled template

[`templates/rectangle.gcode.disabled`](templates/rectangle.gcode.disabled) is
a human-readable sample, not a runnable program.  Generate a machine-specific
review file instead of renaming the template.
