# Indus3D Lab

`indus3d_lab` is a deliberately **read-only** field toolkit for validating an
Indus3D deployment before enabling closed-loop controls or motion tests.  It
does not send G-code, change temperatures, restart services, or write to a
printer.  Its output is portable JSON/JSONL/Markdown so a run can be compared
with an actual print, a simulation, or another host.

## What is included

- `collect_system_stats.py` — captures CPU, memory, load, disk, process, and
  systemd service accounting.  This makes the Indus3D/Mainsail resource
  comparison repeatable.
- `capture_print_telemetry.py` — records the safe `GET /api/v1/telemetry` and
  `GET /api/v1/health` endpoints at a fixed interval.  It never calls a
  control endpoint.
- `analyze_print_run.py` — turns a capture into a numerical summary: sample
  count, state transitions, temperatures, speed/flow, kinematic path length,
  observed velocity, and timing.
- `compare_prediction_reality.py` — compares offline/slicer predictions with
  captured real-world metrics, quantifies model error, and writes review-only
  recommendations. It never changes a printer setting.
- `check_printer_link.py` — compares Klipper's configured MCU serial paths
  with currently detected devices. It never restarts firmware or sends G-code.
- `calibration/` — review-only resonance, thermal, extrusion, and flow test
  artifact generators, validators, and human approval records. They contain no
  upload or execution capability; see `calibration/README.md`.

Future motion-test G-code belongs in a separate reviewed library.  Do not add
or run motion G-code here until the printer is homed, the MCU is healthy, and
the operator has explicitly approved the exact program.

## Quick start

Run these on the NixOS host, or copy this directory there.  Python 3.9+ and
the standard library are sufficient.

```bash
# Passive system + service snapshot
python3 collect_system_stats.py --service indus3d --service moonraker --service klipper --service nginx --output snapshots/baseline.json

# Capture a 30-minute real print (no printer commands are sent)
python3 capture_print_telemetry.py --duration 1800 --interval 1 --output runs/part-001.jsonl

# Create comparable JSON and Markdown reports
python3 analyze_print_run.py runs/part-001.jsonl --output-dir reports/part-001

# After reconnecting a controller or USB hub, diagnose link availability only
python3 check_printer_link.py
```

When dashboard authentication is enabled on the NixOS host, pass its protected
environment file. The script sends it only as a Bearer credential to the two
allow-listed, read-only endpoints and never writes it to a capture:

```bash
python3 capture_print_telemetry.py --duration 1800 --interval 1 \
  --password-file /var/lib/indus3d/indus3d.env --output runs/part-001.jsonl
```

For a Mainsail comparison, take snapshots while both dashboards are idle, then
again while their browser tabs are open.  Compare `services.*.cpu_usage_usec`,
`services.*.memory_current_bytes`, and the process RSS fields rather than
using a single `top` sample.

## Prediction versus reality

Keep a predicted JSON object and an actual-measurement JSON object with only
the values that are genuinely comparable. Supported predicted values are
`elapsed_time_s`, `energy_wh`, `filament_g`, `extruder_temp_c`, `bed_temp_c`,
`path_length_mm`, `position_error_mm`, and `vibration_rms`; actual time is
named `actual_time_s`. For example:

```bash
python3 compare_prediction_reality.py \
  --predicted expected.json --actual measured.json \
  --slicer-estimate-seconds 3600 \
  --output-json reports/part-001/model-error.json \
  --output-markdown reports/part-001/model-error.md
```

The result gives signed residuals, relative error, tolerance status, and
investigation recommendations. It does not apply PID, flow, speed, shaper, or
any other setting automatically.

## Attach a run to the Indus3D Printer Lab

The **Printer Lab** page records the evidence and comparisons; it does not run
these tools or control the printer. After a capture, create one experiment in
the dashboard and attach the paths below:

- **Telemetry capture**: the JSONL from `capture_print_telemetry.py`.
- **Derived report**: the Markdown report from `analyze_print_run.py`.
- **Photos**: paths to photos of the completed part or calibration specimen.
- **Measurements**: observed duration, energy, filament, Indus3D CPU/RAM, and
  Mainsail CPU/RAM from comparable snapshots.

Use one completed idle run as the first baseline. The dashboard then displays
resource deltas for later idle, heating, calibration, and ordinary-print runs.
Its starter budgets are conservative operating targets, not a safety envelope;
replace them with measured limits once enough stable runs exist.

## Data and safety notes

For an already-running print, `observe_print.py` can index a growing telemetry
capture into a separate SQLite database and sample service accounting every
10 seconds. It reads no printer APIs and does not modify the production DB:

```bash
python3 observe_print.py runs/current.jsonl --database runs/current.sqlite
python3 summarize_observation.py runs/current.sqlite --output reports/current.json
```

The observer stops two minutes after an observed printing/paused state changes
to a terminal state, or after its bounded duration (30 minutes by default).
The separate telemetry producer remains bounded by its own duration. Reports
flag absent accelerometer streaming and suspicious zero-power readings.

- Captures can include printer status, file names, and temperatures. Keep them
  outside the public repository unless you intentionally want to share them.
- Failed HTTP samples are recorded as errors and the capture continues. This
  lets a report show outages instead of silently dropping them.
- The toolkit treats an MCU error or offline telemetry as a test failure, not
  as permission to recover the printer.
