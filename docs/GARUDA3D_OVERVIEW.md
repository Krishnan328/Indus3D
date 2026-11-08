# Indus3D — Technical Overview for Garuda3D

*Prepared for internal review and collaboration discussion.*
*This document describes the project at its current stage of development.*

---

## What Is Indus3D

Indus3D is an open-source real-time monitoring and analytics platform for
FDM 3D printers running Klipper firmware. It runs on the printer's existing
single-board computer and connects to Klipper through the standard Moonraker API.

It does not replace Klipper, Mainsail, or any existing printer firmware.
It runs alongside them on the same hardware, on a separate network port,
without modifying the printer's core operation.

---

## The Problem It Addresses

Existing printer monitoring tools — Mainsail, Fluidd, OctoPrint — are dashboards.
They display what the printer's sensors report. They do not model what the
printer *should* be doing or detect when those two things diverge.

Three specific gaps Indus3D addresses:

**1. Mechanical degradation is invisible until failure.**
Belt stretch, bearing wear, and lead screw wear accumulate over thousands of hours.
No existing consumer tool measures cumulative axis travel, direction reversals,
or heat cycles. Operators discover these problems when print quality has already
degraded or a mechanical failure occurs.

**2. Closed-loop quality corrections require hardware access.**
Bambu Lab implements automatic speed and flow adjustments internally on its
printers. On open-platform printers, this capability does not exist in software.
A Klipper printer with worn belts or a slightly miscalibrated extruder will
continue printing at incorrect parameters indefinitely.

**3. Print data is not retained.**
No standard Klipper tool records sensor state, motor commands, or thermal
behaviour at print time for later analysis. This makes fault investigation,
quality auditing, and fleet maintenance scheduling impossible.

---

## What Indus3D Does

### Real-time monitoring
Polls Klipper state at 10 Hz. Displays temperature, position, velocity,
and print progress in a live 3D dashboard accessible from any browser on
the local network.

### Mathematical models running in parallel
Three physics-informed models run alongside every print:

**Kinematic model** — computes positional lag (commanded vs actual position),
derived velocity and acceleration, direction reversals per axis, and cumulative
lifetime odometry in metres. Persisted to a local database across restarts.

**Thermal model** — runs a shadow PID controller using the same kP/kI/kD
constants as Klipper, compares output to actual heater PWM, and counts
heat cycles per heater. Flags anomalous heater behaviour independently of
Klipper's own safety system.

**Extrusion model** — computes volumetric flow rate (mm³/s) from extruder
motor commands and compares it to expected flow from toolhead velocity and
print geometry. Detects E-axis command mismatches. Honest limitation: cannot
detect hardware under-extrusion where the stepper motor is commanding correctly
but flow is restricted by a clog.

### Automated quality corrections
During printing, the system can send corrective G-code commands:

- `M221` (flow rate) — if volumetric flow deviates from expected by more
  than ±4%, adjusts extruder feed rate. Clamped to 85–115%.
- `M220` (print speed) — if positional lag exceeds 0.3mm, reduces speed
  proportionally and restores gradually as lag clears.
- `SET_INPUT_SHAPER` — on Cartesian bed-slinger printers, adjusts Y-axis
  input shaper frequency as part mass increases during the print.
  Requires one-time calibration per printer. Status: implemented,
  requires experimental validation.

### Maintenance scheduling
Alerts fire when axis odometry, heat cycles, or stress scores cross
configurable thresholds. Designed for print farm use where knowing when
to service specific printers reduces unexpected failures.

### Full audit trail
Every print is recorded to a SQLite database at 10 Hz. Position, temperature,
velocity, and model outputs are all retained. This enables post-print analysis,
fault investigation, and quality documentation.

---

## What It Is Not

- Not a slicer. It does not generate or modify G-code before printing.
- Not a replacement for Klipper. It runs alongside Klipper without modifying it.
- Not a cloud service. All data stays on the printer's own hardware.
- Not yet validated for production use. This is an active development project.

---

## Technical Requirements

| Requirement | Notes |
|---|---|
| Firmware | Klipper with Moonraker API |
| Host computer | Raspberry Pi 4 or newer recommended |
| Network | Local network access (no internet required) |
| Storage | ~500MB for software + database |
| Additional hardware | None required. Optional: BME280 sensor, power monitor |

---

## Current Development Status

The software platform is functional and tested on a Creality CR10S Pro V2
with Klipper running on a Raspberry Pi 5. The core monitoring, modelling,
and dashboard components are operational.

Features currently working:
- Live dashboard with 3D toolpath visualisation
- All three mathematical models running during prints
- Automated M221/M220 corrections
- Maintenance alert system
- Full print history database
- Simulation mode for offline development and demonstration

Features in active development:
- Camera-based visual monitoring (toolhead-mounted + chamber)
- Direct drive toolhead upgrade with CAN bus sensor integration
- Vibration-based fault detection using onboard accelerometers
- Filament material profiles for improved extrusion modelling

---

## Collaboration Interest

The project is open source under GPL v3. The public repository is available
at github.com/Krishnan328/Indus3D.

Areas where manufacturer collaboration could be valuable:

**Hardware integration** — Integrating Indus3D more tightly with specific
printer hardware (dedicated sensor ports, factory-calibrated profiles) would
reduce setup friction for end users.

**Validation dataset** — Running Indus3D across a fleet of production printers
would generate the failure data needed to validate the thermal model and refine
maintenance thresholds.

**Open API contribution** — The Moonraker API integration could serve as a
reference implementation for an industry standard monitoring interface for
open-platform printers.

---

*For technical questions or to arrange a live demonstration, contact the developer directly.*
