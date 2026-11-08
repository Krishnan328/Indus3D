# Review-only calibration test library

This library generates bounded G-code artifacts for manual, supervised Klipper
use. It has no Moonraker client, upload endpoint, job queue, or execute command.

- `resonance` uses `TEST_RESONANCES`, but never saves or applies shaper values.
- `thermal` performs a bounded heat-and-hold observation and ends with
  `TURN_OFF_HEATERS`; it never runs PID tuning or saves values.
- `extrusion` is a marked-filament extrude-only check, capped at 50 mm.
- `flow` prints a small first-layer square inside a verified envelope, with
  relative extrusion capped at 50 mm.

Motion-only travel paths remain in `../motion/` and have their own guardrails.

## Required human workflow

1. Confirm the printer is ready, physically clear, and has **no active job**.
   Home/preheat manually where the individual test requires it; keep an
   emergency stop accessible.
2. Generate only a review artifact:

   ```bash
   python3 generate_calibration_test.py --test flow \
     --x-max 250 --y-max 250 --z-max 250 --margin 25 --output flow.gcode.review
   ```

3. Validate and inspect it:

   ```bash
   python3 validate_calibration_gcode.py flow.gcode.review \
     --x-max 250 --y-max 250 --z-max 250 --margin 25
   ```

4. Bind manual review and physical preflight to the artifact hash:

   ```bash
   python3 approve_review.py flow.gcode.review --reviewer operator \
     --acknowledge "I reviewed this artifact and completed the physical preflight"
   ```

5. Only an operator can separately decide whether to manually upload and run
   the reviewed program. Indus3D and this toolkit cannot do that step.

After a supervised test, attach its `.review`, `.approval.json`, telemetry
capture, derived report, and photographs to a Printer Lab experiment.
