# Indus3D — Complete Development Context
## For starting a new Claude coding session with full project knowledge

---

## Project Identity

**Name:** Indus3D
**Type:** Real-time digital twin and monitoring platform for Klipper-based FDM 3D printers
**Developer:** Krishnan (student, startup founder, India)
**GitHub:** Krishnan328/Indus3D — preview build on `codex/packaging-fixes`; `main` remains the stable branch.
**Stage:** Active development. Backend and frontend both functional. Tested against real hardware.
**Goal:** Startup product targeting 3D printer manufacturers (initial contact made with Garuda3D)

---

## Hardware Context

**Primary printer:** Creality CR10S Pro V2
- 300×300×400mm Cartesian bed-slinger
- Klipper firmware + Moonraker API
- Raspberry Pi 5 as host computer (accessed via Tailscale VPN)

**Planned hardware upgrade (sourced, not yet assembled):**
- Biqu Nebula extruder (direct drive)
- BTT EBB36 Gen2 CAN bus toolhead board (onboard ADXL345)
- Bambu-style hotend E3 v2.0
- 2× 5010 blower fans + 4020 hotend fan
- Mantis Dual 5015 toolhead shroud (community port for CR10/Ender)
- MGN12H 300mm rail for X axis
- MGN15H rails for Y axis (bed)
- BTT U2C V2.1 OR Raspberry Pi Pico + SN65HVD230 as USB-to-CAN bridge
- Raspberry Pi Pico as USB bridge for BME280 + bed ADXL345
- ESP8266 as wireless relay for PZEM-004T power monitor (galvanic isolation)
- USB endoscope/Arducam for toolhead camera

**Dev environment:** macOS (primary), Pi 5 via VS Code Remote-SSH + Tailscale

---

## Repository Structure

```
indus3d/
├── backend/
│   ├── main.py                    # Entry point. --sim flag for simulation mode
│   ├── .env                       # Machine-specific config (never committed)
│   ├── .env.example               # Template
│   ├── requirements.txt
│   ├── config/
│   │   ├── settings.py            # SINGLE SOURCE of all config (env vars + .env)
│   │   ├── cfg_parser.py          # Parses Klipper printer.cfg sections
│   │   ├── loader.py              # Profile priority chain: Moonraker→local→JSON
│   │   ├── indus_overrides.cfg    # Non-Klipper values (thresholds, shaper baseline only —
│   │   │                          #   Moonraker address is NOT here, see below)
│   │   └── printer_profile.json  # Fallback profile (no Moonraker)
│   ├── digital_twin/
│   │   ├── state.py               # Thread-safe PrinterState singleton
│   │   ├── kinematic_model.py     # Odometry, lag, velocity, reversals, stress
│   │   ├── thermal_model.py       # Shadow PID, heat cycles, runaway detection
│   │   ├── extrusion_model.py     # Volumetric flow, flow ratio, LA pressure estimate
│   │   ├── quality_controller.py  # M221/M220/SET_INPUT_SHAPER closed-loop control
│   │   ├── snapshot_logger.py     # Writes per-tick snapshots to SQLite
│   │   └── filament_profiles.py   # Material density database (PLA, ABS, PETG, etc.)
│   ├── workers/
│   │   ├── telemetry_worker.py    # 10Hz Moonraker poll, runs models, live_commands
│   │   ├── simulator.py           # Full offline sim: corrected Benchy, 20 waypoints/tick
│   │   └── gcode_shapes.py        # Synthetic G-code generator (benchy + cube)
│   ├── api/
│   │   ├── server.py              # Flask app factory, WebSocket, all routes registered.
│   │   │                          #   /api/control/execute lives directly on app here.
│   │   └── routes/
│   │       ├── printer.py         # ALL Moonraker proxy routes (critical: no direct :7125)
│   │       ├── twin.py            # Digital twin endpoints + alert action endpoints
│   │       ├── sim.py             # Sim-specific endpoints incl. /api/sim/gcode_file
│   │       └── profile.py         # Printer profile endpoints
│   ├── services/
│   │   └── moonraker_client.py    # HTTP client for Moonraker (settings.moonraker_url)
│   ├── core/
│   │   └── alert_actions.py       # Automated corrective G-code per alert type
│   ├── edge/                      # NOT wired into the app yet — roadmap (camera/YOLO pipeline)
│   │   ├── watchdog.py            # MOG2 background subtraction spaghetti detector
│   │   ├── harvester.py           # Frame capture on layer change
│   │   └── inspector.py          # YOLOv8 defect classification
│   └── db/
│       └── models.py              # SQLite schema: snapshots, odometry, action_log, etc.
└── frontend/
    └── src/
        ├── App.jsx                # Root: 3D scene, modals, sidebar layout
        ├── store.js               # Zustand store: ALL state + WebSocket
        ├── GCodeVisualizer.jsx    # Parses and renders G-code path in Three.js
        ├── CameraFeeds.jsx        # Multi-camera from Crowsnest
        ├── PrintStatusCard.jsx    # Progress, ETA, pause/resume/cancel, upload
        ├── QualityPanel.jsx       # Quality controller live gauges + correction log
        ├── ActionLog.jsx          # Automated corrective action history
        ├── PrintBed.jsx           # 3D bed mesh from profile dimensions
        └── ProfileBar.jsx         # Printer name, profile source, reload button
```

**Removed in patch8** (dead code audit — see "Fixed in patch8" below for why):
`api/routes/telemetry.py`, `api/routes/control.py`, `cmd_queue/`, `workers/queue_worker.py`,
`core/logger.py`, empty `ipc/` and `utils/` scaffold dirs.

---

## Architecture — Critical Facts

### Data flow (preserve this exactly)
```
TelemetryWorker (10Hz) → printer_state singleton → 3 digital twin models
→ quality_controller → telemetry_worker.latest dict → Flask WebSocket
→ frontend store.js → React render
```

The simulator is a drop-in replacement for TelemetryWorker. Same `.latest` dict shape.

### Frontend never calls port 7125 directly
ALL Moonraker access goes through Flask `/api/printer/*` proxy routes.
This is the most important architectural rule. Without it, dev machine testing fails.
- G-code files: `GET /api/printer/files/gcodes/<filename>`
- Config files: `GET /api/printer/config/list`, `GET /api/printer/config/<name>`
- Bed mesh: `GET /api/printer/bedmesh`
- Camera list: `GET /api/printer/cameras`
- Webcam stream URL: `GET /api/config` → `webcam_stream_url`

### Configuration hierarchy
```
.env file (machine-specific, never committed)
    → config/settings.py singleton (import settings; settings.MOONRAKER_HOST)
    → config/loader.py (reads printer.cfg from Moonraker, builds profile dict)
    → config/indus_overrides.cfg (non-Klipper values ONLY: thresholds, shaper baseline,
       print geometry defaults — moonraker_ip/moonraker_port were removed from here
       in patch8, see below)
```

As of patch8, `settings.moonraker_url` is genuinely the only source for the Moonraker
address — `loader.py`, `cfg_parser.py`, and `MoonrakerClient` all resolve through it.
This was NOT true before patch8; see "Fixed in patch8" for what was actually broken.

Never call `os.getenv()` outside of `settings.py`. Never hardcode IPs.

### Coordinate system (3D viewport)
```
Printer X → scene X (unchanged)
Printer Z (height) → scene Y
Printer Y → scene Z = (bed_size_y_mm/10) - (cmd_y / 10)   ← Y is FLIPPED
```
The Y flip makes front of printer = front of 3D viewport.
Both Toolhead useFrame AND GCodeVisualizer must use this same mapping.

### Sim mode detection
Filename prefix `sim_` identifies simulation files. GCodeVisualizer fetches from
`/api/sim/gcode_file` if filename starts with `sim_`. Never rely on `simMode` flag
for URL selection (timing issue). `simMode` in store latches once true, never resets.

### Byte offset alignment (critical — do not change)
Backend `gcode_shapes.py` computes waypoint bytes as:
```python
line_bytes = len((line + "\n").encode("utf-8"))
byte_at_end_of_line = cumulative_byte + line_bytes
```
Frontend `GCodeVisualizer.jsx` matches with:
```javascript
const lineByteLength = encoder.encode(lineWithNL).length;
// where lineWithNL = rawLine + "\n" for all lines except last
```
`file_position` from Moonraker/simulator must match these offsets or the visualizer
shows nothing. The simulator sets `file_position = waypoints[wp_idx]["byte"]`.

### Alert guard (critical)
Lag and extrusion alerts only fire during `print_state === "printing"`.
Thermal runaway alerts always fire. This prevents false positives during homing.
This guard exists in `store.js` `deriveAlerts()` — do not remove it.

### Extrusion model — honest scope
The flow ratio compares commanded E position to expected flow from velocity × geometry.
It detects SLICER misconfiguration, not hardware under-extrusion.
Stepper motors have no force feedback. Partial clogs are not detectable this way.
The "pressure estimate" is `K × velocity` (LA compensation term), not a measured pressure.

### Simulator behaviour
- Pre-builds gcode_str in `__init__` (before first tick) so `/api/sim/gcode_file` always has content
- Sets temps INSTANTLY (instant=True) — no heating delay
- Expands the 0.4 mm source contours into a continuous 0.2 mm, 240-layer Benchy preview
- Advances `WAYPOINTS_PER_TICK = 20` at 10Hz; physical extrusion is calculated from bead geometry
- Uses simulator ground truth for the time-compressed flow ratio so normal prints do not fabricate M221 corrections
- Quality controller commands appear in `gcode_feed` via `inject_quality_command()`
- Faults injected at t=60s (runaway), 120s (under-extrusion), 180s (lag spike), 240s (over-extrusion)

---

## Mathematical Models

### Kinematic model
```
ΔX = |cmd_x[t] - cmd_x[t-1]|  (with 0.05mm deadband)
odometry_X += ΔX / 1000  (metres)

lag_x = cmd_x - live_x
lag_magnitude = √(lag_x² + lag_y² + lag_z²)

v_derived = √(Δlive_x² + Δlive_y² + Δlive_z²) / Δt

if sign(Δpos[t]) ≠ sign(Δpos[t-1]):
    reversal_count += 1
    stress_score += 0.001
```

### Thermal model
```
Shadow PID:
    P = kP × error
    I = kI × Σ(error × Δt)
    D = kD × (error[t] - error[t-1]) / Δt
    PWM_shadow = (P + I + D) / 100

pid_delta = |PWM_shadow - PWM_actual|

Runaway: avg_pwm > 0.8 AND temp_drop > 15°C in 5 seconds
Heat cycle: cold→hot→cold transition
```

### Extrusion model
```
filament_area = π × (filament_dia/2)²
feed_rate = Δcmd_e / Δt
volumetric_flow = feed_rate × filament_area

bead_area = (nozzle_d - layer_h) × layer_h + π × (layer_h/2)²
expected_flow = velocity × bead_area

flow_ratio = volumetric_flow / expected_flow
under_extrusion: flow_ratio < 0.80
over_extrusion:  flow_ratio > 1.25

LA pressure estimate = K × velocity
```

### Quality controller
```
Flow: M221 S{int(100 + error × FLOW_KP × 100)}   clamped [85,115]  interval 8s  deadband ±4%
Speed: M220 S{int(speed - lag_mm × SPEED_KP)}    clamped [50,100]  interval 3s
Shaper: f_new = f_baseline × √(m_baseline / m_total)   interval 30s  threshold 0.5Hz
    where m_total = m_baseline + filament_mass_g
    part_mass_g = filament_consumed_mm × π × (dia/2)² × density_g_cm3 / 1000
```

---

## Key Dependencies

**Backend:** Python 3.10+, Flask, flask-sock, flask-cors, requests, python-dotenv, sqlite3
**Frontend:** React 18, Three.js, @react-three/fiber, @react-three/drei, Zustand, Tailwind CSS
**Printer stack:** Klipper, Moonraker, Mainsail, Crowsnest
**Ports:** Flask API=5001, WebSocket=5001/ws/twin, Moonraker=7125 (Pi-internal only), Vite dev=5173

---

## Known Issues and Current State

### Fixed in patch7
- All direct port 7125 calls replaced with Flask proxy routes
- Alert false positives during homing (added print_state guard)
- Ambient temp showing 200+°C (was using extruder temp as fallback)
- G-code terminal showing "Awaiting Print Job" during active print
- M220/M221 not visible in terminal (now appears as [QC] prefix)
- Bed orientation flipped front-to-back (Y axis mapping fixed)
- Config editor showing no files (was calling port 7125 directly)
- Multiple camera feeds via CameraFeeds.jsx component

### Fixed in patch8 (most recent — dead code audit + config bug)
- **Dead code removed as one coherent audit**, verified by import-tracing and
  endpoint-registration checks (not by file dates):
  - `api/routes/telemetry.py` — an orphaned Blueprint, never registered in
    `server.py`. Its 3 routes were already superseded elsewhere: `/environment`
    by the top-level `/api/environment`, `/odometry` by `/api/twin/odometry`;
    `/logs` had no replacement and nothing called it.
  - The entire Stage 1 command-queue subsystem — `cmd_queue/`,
    `workers/queue_worker.py`, `api/routes/control.py`, `core/logger.py`.
    `control.py`'s own comment admitted it: its `/api/control/execute` route
    was shadowed by the one defined directly on `app` in `server.py`, so
    `CommandQueue.enqueue()` was never called and `QueueWorker` just busy-looped
    on an empty queue forever. Confirmed via grep that nothing else touched
    `.enqueue()` or `get_queue()`. `main.py` and `server.py` updated to drop
    the wiring; the live `/api/control/execute` route itself was untouched.
  - Empty scaffold dirs `ipc/`, `utils/` — zero files, zero imports.
- **Fixed a real (not cosmetic) config bug**: `config/loader.py` and
  `config/cfg_parser.py` each independently read `moonraker_ip`/`moonraker_port`
  out of `indus_overrides.cfg`, while `config/settings.py` independently read
  `MOONRAKER_HOST`/`MOONRAKER_PORT` from `.env` — two different defaults
  (`100.88.38.105` vs `127.0.0.1`). `MoonrakerClient` (used by `alert_actions.py`
  and by `telemetry_worker.py` for sending corrective G-code) resolved via the
  `indus_overrides.cfg` path, while the proxy routes and the worker's polling
  loop resolved via `.env`. If the two files ever disagreed — e.g. updating
  `.env` when moving from the Mac to the Pi and forgetting `indus_overrides.cfg`
  — corrective G-code could silently target a different Moonraker instance
  than the one being polled. Fixed by making `settings.moonraker_url` the one
  real source everywhere; `indus_overrides.cfg` no longer carries a Moonraker
  address at all. Verified at runtime: injecting a divergent `MOONRAKER_HOST`
  env var now correctly propagates all the way to `MoonrakerClient.base_url`
  (it did not, before the fix).
- `README.md` rewritten, structured after Klipper's and Mainsail's READMEs —
  added a "Project status" section (validated vs. not-yet-validated, same
  spirit as `docs/DEVELOPMENT.md`), a Features list, Acknowledgments crediting
  Klipper/Moonraker/Mainsail, and removed stale "git init" boilerplate.

### Known remaining issues
- Extrusion path in 3D viewport may not render on first load (file fetch timing)
  → GCodeVisualizer has retry logic (8 retries × 500ms)
- Sim mode: path renders only after `sim_benchy.gcode` filename appears in WebSocket
  → filename set when state transitions to "printing" (~5 seconds after start)
- `profile_source` shows "printer_profile.json (fallback)" if Moonraker unreachable
  → expected on dev machine without Pi connected; profile is read-only on startup
- `backend/edge/watchdog.py`, `harvester.py`, `inspector.py` still hardcode
  `PI_IP = "100.88.38.105"` directly. Harmless today since none of `edge/` is
  wired into the running app yet, but when it is wired in, route it through
  `settings.moonraker_url` — otherwise this reintroduces the exact bug fixed
  in patch8, just in a third place.
- `backend/config/indus_sim_ender3.cfg` still has inert `moonraker_ip`/
  `moonraker_port` lines left over from before patch8. Harmless — that file
  is only ever used as the sim "printer.cfg" equivalent, never as the
  overrides file, so those two lines were never actually read even before
  the fix. Cosmetic cleanup only, low priority.

### Pending features (roadmap)
- Moonraker WebSocket subscription replacing HTTP polling (50Hz upgrade)
- Vibration analysis pipeline using EBB36 ADXL345 at 3200Hz
  → Rust PyO3 module for FFT/PSD/kurtosis computations
  → Calibration print: hollow octagon, multiple speeds, multiple heights
  → Self-calibrating baseline (per-printer, no manual threshold setting)
- Sensor bridge Python code for Pico USB serial (BME280 + ADXL345 + VL6180X ToF)
- PZEM-004T integration via ESP8266 HTTP relay
- Variable input shaping: experimental validation required before further development
  → Print ringing test pattern at 0%, 50%, 100% print height
  → Measure if ringing amplitude changes with mass
- Layer height measurement via VL6180X ToF sensor on toolhead
- Laser structured-light layer quality inspection (future)
- Multi-printer architecture for fleet management
- Database migration system (ALTER TABLE for schema changes)
- API versioning (/api/v1/)
- API key authentication for multi-user environments

---

## Development Workflow

```bash
# On Pi (or Mac with sim):
cd backend && source indus_env/bin/activate
python main.py --sim                    # sim mode (benchy)
python main.py --sim --shape cube       # calibration cube
python main.py                          # live mode (Pi only)

# Frontend:
cd frontend && npm run dev -- --host   # expose on network

# Access: http://<machine-ip>:5173
# API:    http://<machine-ip>:5001
# Health: http://<machine-ip>:5001/api/health
```

**VS Code Remote-SSH** to Pi is the preferred dev workflow for hardware-in-loop testing.

---

## File Placement Guide for New Chat Sessions

When asking Claude to write code for this project, specify:
- `backend/config/settings.py` — centralized config
- `backend/api/routes/printer.py` — ALL Moonraker proxy routes
- `backend/api/server.py` — Flask app, registers all blueprints
- `backend/workers/telemetry_worker.py` — main live worker
- `backend/workers/simulator.py` — simulation worker
- `frontend/src/store.js` — all frontend state + WebSocket
- `frontend/src/App.jsx` — root component (large, ~600 lines)
- `frontend/src/GCodeVisualizer.jsx` — standalone 3D path renderer

---

## What Has Been Explicitly Validated

1. Dashboard renders live Klipper data during a real benchy print ✅
2. Nozzle position tracks in real time in 3D viewport ✅
3. Alerts fire during print (lag, under-extrusion) ✅
4. Sim mode builds benchy/cube shape visually in ~60-90 seconds ✅
5. Quality controller sends M221/M220 during sim (visible as [QC] in terminal) ✅
6. Print history written to DB after completed sim print ✅
7. Odometry accumulates correctly with deadband filtering ✅

## What Has NOT Been Validated

1. Variable input shaping benefit (theoretical — needs ringing test)
2. Flow ratio model detecting real hardware under-extrusion
3. Shadow PID delta as a heater failure predictor
4. Vibration-based fault detection (not yet implemented)
5. Camera pipeline integration with digital twin data
6. Multi-printer support

---

## Product/Business Context

**Garuda3D meeting outcome:**
- Founder liked the concept but questioned two specific features:
  1. Variable input shaping (claims no measurable problem on well-tuned machines)
  2. Flow ratio correction (may not solve real problems on calibrated printers)
- Response: validate experimentally before including in product pitch
- Document prepared for their internal review (docs/GARUDA3D_OVERVIEW.md)

**Validated differentiators:**
- Platform-agnostic (works on any Klipper printer, unlike Bambu ecosystem)
- Odometry-based predictive maintenance (no existing tool does this)
- Full audit trail via SQLite snapshot log
- Open API for integration with fleet management systems

**What requires experimental evidence before pitching:**
- Variable input shaping benefit
- Flow correction improving dimensional accuracy
- Thermal model predicting heater failures

---

## Common Mistakes to Avoid

1. Never hardcode `localhost:7125` or any IP in frontend code
2. Never call Moonraker directly from frontend — always through `/api/printer/*`
3. Never fire alerts outside `print_state === "printing"` (except thermal runaway)
4. Never change byte counting method in gcode_shapes.py or GCodeVisualizer.jsx
5. Never import `os.getenv()` outside `config/settings.py`
6. Never remove the `sim_` filename prefix — GCodeVisualizer uses it for URL routing
7. The Y coordinate in the 3D scene is FLIPPED: `scene_z = bedY - cmd_y/10`
   Both Toolhead component AND GCodeVisualizer must use this mapping
8. `simMode` in store latches true and never resets mid-session
9. Never add a second config source for a value `settings.py` already owns
   (this is literally what patch8 had to fix for the Moonraker address)

---

## Session Notes — Important Context for Next Session

> Note: this whole section was present in the context document pasted into
> chat at the start of a session but was missing from CLAUDE_CONTEXT.md as
> saved in the repo — i.e. the handoff doc had already drifted from what's
> on disk once. Restored here in patch8; keep this file and what you paste
> in sync going forward.

### On the benchy comparison test
- If printer is well-calibrated, benchy with and without Indus3D may look identical — this is CORRECT behaviour, not a failure
- M221/M220 not firing = printer was already within deadbands = good calibration
- Interesting result to watch for: if corrections fire, note the values and measure wall thickness with calipers
- Target: benchy hull wall thickness = your slicer line width setting (typically 0.4mm)
- The CR10S Pro V2 has a Bowden tube fault and is NOT operational — fix this before any comparative testing

### Most important technical debt (highest priority refactor)
- `loader.py` `_refresh_module_attrs()` pattern is the most fragile part of the backend
- It silently reassigns module-level variables (`bed`, `motion`, `hotend`, `bed_heater`, `print_cfg`, `alerts_cfg`) after profile reload
- This has caused bugs before and will again — patch8 fixed the `moonraker_url` leg
  of this specifically (it's no longer part of the reassigned profile dict, it
  delegates to `settings` directly), but the broader pattern for the *other*
  five attributes is untouched and still the highest-priority structural refactor
- Fix: every module should import `settings`/`loader` and call `get_profile()`
  (or the relevant `get_*()`) explicitly instead of importing the module-level
  shortcut at import time
- Estimated time: 2 hours. Do this in a quiet session with no feature pressure.

### CLAUDE_CONTEXT.md maintenance
- Update this file after every significant dev session
- Sections to keep current: known issues, validated features, roadmap
- If this file doesn't reflect current state, it's useless as a context primer
- As of patch8: it didn't — see the note at the top of this section

### Garuda3D document caution
- Don't send GARUDA3D_OVERVIEW.md without verifying every "currently working" claim
- A manufacturer who asks a follow-up on a non-working feature loses confidence fast
- Better to list fewer features confidently than more features speculatively

### Product positioning insight (important)
- Garuda3D founder pushed back on variable input shaping: "well-tuned machines don't have this problem"
- This is correct — but the target market is NOT manufacturers with perfectly tuned machines
- Real audience: the majority of users who don't know their machine is miscalibrated and have no tool to tell them
- This reframe is more persuasive than defending any specific feature technically

### Hardware shopping list status
- Raspberry Pi Pico + SN65HVD230 confirmed as valid USB-to-CAN bridge (Klipper official docs)
- Saves ~₹5,800 vs BTT U2C V2.1
- Need TWO Picos: one for CAN bridge (+ SN65HVD230), one for BME280 + bed ADXL345
- Confirm both Picos ordered before hardware assembly session

### Patch history summary
- patch1-3: Initial platform, WebSocket, digital twin models, basic dashboard
- patch4: Sim mode shapes (benchy/cube), byte-accurate file_position
- patch5: Quality controller (M221/M220/SET_INPUT_SHAPER), QualityPanel, sim fixes
- patch6: Sim heating delay fixed (instant temps), WAYPOINTS_PER_TICK=5, path rendering fix
- patch7: All Moonraker proxied through Flask, alerts guard, Y-flip fix,
  live_commands terminal, CameraFeeds multi-camera, filament_profiles, settings.py,
  DEVELOPMENT.md, GARUDA3D_OVERVIEW.md
- patch8: Dead code audit (telemetry.py, empty ipc/+utils/, entire
  command-queue subsystem removed as a verified-unreachable group); fixed the
  dual-config-source Moonraker URL bug (`settings.py` is now genuinely the only
  source); README.md rewritten in Klipper/Mainsail style
- patch9: Frontend theme system + layout redesign. Three themes —
  classic (original dark/light, byte-identical to pre-patch9), workshop and
  blueprint (brutalist: thick black borders, hard offset shadows, square
  corners, pastel fills) — switchable at runtime via `theme.js` tokens, no
  page reload, persisted to localStorage. New primary "Dashboard" page is a
  fixed 2-row grid (viewport/status/quality/temps, then actions/console/
  camera) sized to fit one screen without scrolling — viewport went from a
  dominant hero panel to one-of-four, with a click-to-expand fullscreen
  toggle for when you actually want to stare at the print. Everything that
  was in the old "Live" + "Digital Twin" sidebar tabs still exists — it's
  reorganized into Dashboard (glanceable) vs a new "Digital Twin" nav page
  (deep model internals, odometry, power/environment, print history,
  maintenance, replay) rather than removed. PrintStatusCard, QualityPanel,
  ActionLog, CameraFeeds, ProfileBar, GCodeVisualizer, PrintBed, and all
  store.js data/WebSocket logic are byte-identical to patch8 — only
  App.jsx was rewritten; everything else was either left alone or had its
  color/border/shadow classNames swapped for theme tokens without touching
  logic. Verified via `npm run build` + `npm run lint`, and by diffing the
  moved-verbatim blocks (Terminal, HeightmapModal, ConfigEditor, Toolhead)
  against the pre-patch9 file to confirm zero logic drift.
- patch10: Spoolman filament-inventory integration — first of five
  competitor-derived features being built one at a time (Spoolman, thermal-
  runaway power cutoff, notifications, timelapse, file manager). New
  `printer.py` routes proxy Moonraker's real `[spoolman]` component
  (`/server/spoolman/status`, `/spool_id`, `/proxy` — verified against
  Moonraker's own docs). New `SpoolPicker.jsx` renders inside
  `PrintStatusCard.jsx` (one-line additive insertion) — shows active spool,
  a picker, and — the actual differentiator over Mainsail/Fluidd's spool
  widgets — Indus3D's own `extrusion_model.py`-computed filament usage
  (real volumetric flow) shown next to Moonraker's E-position-based figure.
  Fails closed (quiet message, not an error) if `[spoolman]` isn't
  configured; nothing else depends on it. Verified via build + lint.
- patch11: Thermal-runaway → physical power cutoff (feature 2 of 5).
  **Found and fixed a real reliability bug along the way, independent of the
  new feature**: `execute_alert_action` (including the existing M112
  emergency-stop response) was only reachable via a frontend HTTP call —
  meaning a runaway with no browser tab open would never trigger it.
  `telemetry_worker.py` now calls it directly from its own loop every tick,
  no UI dependency. Power cutoff itself is opt-in (`indus_overrides.cfg`:
  `power_cutoff_enabled`/`power_cutoff_device`), off by default, and is
  layered on top of M112 rather than replacing it — a stuck heater MOSFET
  can keep heating even after Klipper shuts down; only a separate relay
  circuit can stop that. Uses Moonraker's real `[power]` device API
  (`/machine/device_power/*`, verified against Moonraker's docs). Found and
  documented a real footgun: devices with `locked_while_printing=true` in
  moonraker.conf will silently refuse the cutoff during a print — the new
  `PowerPanel.jsx` detects this mismatch client-side and shows a red
  warning. Also fixed a re-arm bug before shipping it: the dedup set would
  have made the response fire once ever, then stay permanently disarmed —
  added edge-tracking in `telemetry_worker.py` so it clears and re-arms
  after each episode resolves. New `services/moonraker_client.py::set_power`,
  new `printer.py` routes (`/power/devices`, `/power/<device>/<action>`,
  `/power/cutoff_config`), new `config/cfg_parser.py::_bool` helper, new
  `power` section threaded through `loader.py`/`printer_profile.json`
  fallback consistently with how `alerts` already worked. Verified with
  direct unit tests (safe defaults, M112-only vs M112+relay, relay-failure
  visibility, non-runaway alerts never triggering a cutoff, and a full
  two-episode re-arm test) plus build + lint.
- patch12: Outbound notifications — Discord webhook + Telegram bot
  (feature 3 of 5). New `core/notifications.py`: small, extensible dispatcher
  (`notify(message)` fans out to every configured channel, add a new one by
  writing one `_send_<name>` function — see its own docstring). Credentials
  (`DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
  `NOTIFY_ON_WARN`) live in `settings.py`/`.env`, matching how `MOONRAKER_HOST`
  is handled — deliberately NOT editable through the UI, since these are
  secrets, not behavior config; `SettingsModal` only shows a read-only
  connected/not-connected status via a new `GET /api/twin/notifications/status`
  route. Two trigger points, both server-side for the same reliability reason
  as patch11's M112 fix: (1) critical/warn alerts notify from inside
  `execute_alert_action` in `alert_actions.py`, alongside the existing
  corrective G-code/power-cutoff — critical always notifies, warn is opt-in
  via `NOTIFY_ON_WARN`; (2) print completion/failure/cancellation notifies
  from a new print_state edge-tracker in `telemetry_worker.py` (`_prev_print_state`),
  firing exactly once per transition, not every tick. Caught and fixed my
  own design smell before shipping: `notify()` originally reported an
  unconfigured channel as "sent" (a no-op silently indistinguishable from a
  real send) — changed to explicit sent/skipped/failed per channel. Verified
  with direct unit tests: unconfigured channels are honest no-ops, correct
  Discord/Telegram payload shapes, a channel exception never propagates out
  of `notify()`, and the print-state transition fires exactly once per real
  event (not on startup, not while state is stable, fires again on a second
  transition) — plus build + lint.
- patch13: Timelapse (feature 4 of 5). New `core/timelapse.py`:
  two capture modes — "layer" (fires on Z increase, using Indus3D's own live
  Z tracking, no slicer macros needed) or "interval" (time-based, works with
  any slicer). Frame source is Crowsnest's `?action=snapshot` convention,
  verified against Mainsail/Crowsnest docs, derived from the existing
  `settings.webcam_stream_url`. ffmpeg invoked as a subprocess (never
  bundled) in a background thread on print completion, so stitching can't
  block the telemetry loop. New `power`-section-style config plumbing
  (`timelapse` section through `cfg_parser.py`/`loader.py`/
  `printer_profile.json` fallback) and a new `settings.TIMELAPSE_DIR`
  (pattern-matched to `DB_PATH`, gitignored the same way).
  **Caught and fixed a real bug while building this — not in the new code,
  in patch11's `power_cfg`**: both `alert_actions.py` (patch11) and my
  first draft of `timelapse.py` did `from config.loader import <x>_cfg` —
  exactly the stale-module-attribute anti-pattern CLAUDE_CONTEXT.md already
  flags under "Most important technical debt." `_refresh_module_attrs()`
  *rebinds* these names to new dict objects on every `reload()`; a module
  that imported the old reference at import time never sees updates.
  Fixed both to call `get_power_cfg()`/`get_timelapse_cfg()` fresh instead
  — the documented correct pattern. Verified the fix is real, not
  cosmetic: reproduced the exact failure mode in a test (a hardcoded-mode
  test silently used the wrong config until the getter fix made it honest),
  then fixed the test and confirmed the full state machine (start → capture
  → dedup-by-Z → finish → background stitch) end-to-end, including a run
  against real generated JPEG frames producing a real, playable, non-empty
  mp4 — not just mocks. Also verified path-traversal protection on the new
  `/timelapse/<job_id>/video` route against real attack strings. New
  `TimelapseGallery.jsx` on the Digital Twin page. Build + lint clean.
- patch14: File manager — feature 5 of 5, closes out the
  competitor-derived feature queue (Spoolman, power cutoff, notifications,
  timelapse, file manager). New "Files" page on the nav rail (third icon).
  Verified Moonraker's real file-manager API from its own docs before
  writing anything: `GET /server/files/metadata`, `DELETE /server/files/
  gcodes/<filename>`, `POST /printer/print/start?filename=`. New backend:
  `GET /api/printer/files/metadata`, `DELETE /api/printer/files/gcodes/
  <filename>` (both in `printer.py`), `POST /api/print/start` (in
  `server.py`, alongside the existing pause/resume/cancel/upload routes).
  Thumbnails need no new route at all — Moonraker's generic file-download
  endpoint already serves any path under `gcodes` including `.thumbs/*.png`,
  so the existing `get_gcode_file` route just works for them.
  **Went down a false-positive path worth recording**: a static grep for
  `/api/print/pause` etc. across the codebase came up empty, which looked
  like the same class of bug as earlier patches (a UI control calling a
  route that doesn't exist). It wasn't — `server.py` registers those three
  dynamically in a loop (`app.route(f"/api/print/{action}", ...)`), which
  a literal-string grep can't see through. Caught it before "fixing"
  anything by actually starting the server and curling the routes for real
  (got proper 502s — "Moonraker unreachable" — not 404s). Worth remembering:
  static analysis said "missing," runtime said "present and correct" —
  runtime wins. No changes were made to those three routes.
  Path-traversal protection on the new delete route tested against both
  plain and URL-encoded traversal attempts — plain `../../` is actually
  blocked by Werkzeug's own routing before reaching the handler; the
  `".." in filename` check earns its keep specifically against the
  URL-encoded form, which Flask decodes before your view function sees it.
  New `FileManager.jsx` + `FileRow` (thumbnail from metadata, size,
  modified date, estimated print time, filament weight; print/delete both
  confirm before acting). Build + lint clean, only pre-existing issues
  remain (re-verified, not introduced by this patch).
- patch15: Hardware efficiency — actually implementing the Tier 1
  plan that was scoped many sessions back but kept getting deferred for
  feature work. Three fixes, all measured, not just argued for:
  (1) `snapshot_logger.py` rewritten — `log_snapshot()` was still doing a
  full connect+insert+commit+close on every tick (confirmed still
  unfixed before touching it); now buffers in memory (measured 0.054ms/call,
  down from a blocking disk write) and a background thread flushes in one
  `executemany()` every 2s on a persistent connection. Verified end-to-end
  with a real temp SQLite DB: 50 calls in 2.71ms total, zero rows in the DB
  before the flush window, all 50 correct after, `get_recent_snapshots()`
  returns them in the right order.
  (2) `requirements.txt` split — confirmed via grep across the whole tree
  (not assumed) that only Flask/requests/python-dotenv are actually
  imported by the running app; moved opencv/ultralytics to
  `requirements-vision.txt` with an explicit companion-device note, dropped
  `psutil`/`websocket-client` entirely (verified zero real usage anywhere,
  including `edge/` — both were for features never built).
  (3) `TWIN_TICK_HZ` — found and fixed a subtlety while doing this: there
  were *two* independent hardcoded `POLL_HZ = 10` constants
  (`telemetry_worker.py` and `simulator.py`), not one. Making only the live
  path configurable would have made sim mode silently diverge from live
  behavior. Both now read the same `settings.TWIN_TICK_HZ`. Verified at
  runtime that the default (10.0) is unchanged and that setting the env var
  actually propagates to both.
  Also populated `.env.example` for the first time since patch7 — it had
  stayed a near-empty placeholder while `settings.py` accumulated a full
  page of real options across patches 10-14. Full smoke test of the
  integrated server (not just isolated unit tests) confirmed real snapshot
  rows land in the DB via the new batched path during actual operation.
- patch16: Shaper Tuner. A safety-gated Digital Twin workflow runs Klipper's
  Y-axis `SHAPER_CALIBRATE`, polls Moonraker's G-code console for the
  recommendation, and saves the confirmed value to `indus_overrides.cfg`
  without discarding its comments. It is not a replacement for Klipper's
  accelerometer analysis and is unavailable during a print.
- patch17: Added the soft Creme theme alongside Classic, Workshop, and
  Blueprint. `useIsSoft()` handles the few light-theme fallbacks that cannot
  be expressed solely through the shared token set.
- patch18: Port robustness. The frontend now reads `VITE_API_PORT` (matching
  backend `FLASK_PORT`), the backend detects a listening-port conflict before
  starting, `main.py` watches daemon service threads, and an optional nginx
  configuration provides a single production port for API, WebSocket, and UI.
- patch19: Simulation and guided calibration dashboard. The Benchy
  preview uses continuous virtual layers and realistic extrusion; temperature
  history, printed-object preview, bounded toolhead controls, and a
  confirmation-gated calibration wizard were added. Flow calibration remains
  measurement-assisted unless a camera or physical sensor is available.
- patch20: Cherry-pick minor improvements from the Indus3D_claude branch
  (which had been developed in parallel by a collaborator and ended at
  patch18). After careful comparison, the main branch was already ahead —
  only watchdog comment clarity (main.py), a more actionable port-conflict
  error message (server.py), and a clarifying NOTE about shaper config
  ownership (settings.py) were cherry-picked. No functional changes.
- patch21: PZEM-004T power monitoring. A new `services/pzem_monitor.py`
  module reads voltage/current/power/energy/frequency/power_factor/alarm
  from a PZEM-004T energy monitor via Modbus RTU over RS485 (USB-serial
  FTDI adapter, directly wired to the Pi — not the ESP8266-HTTP relay
  approach the old roadmap assumed). The module follows moonraker_client.py's
  error-handling pattern: never raises, never blocks, logs rate-limited
  errors, returns None values (not zeros) when disconnected so the frontend
  can distinguish "not connected" from "reading actual zero". Wired into
  telemetry_worker._tick() so power data flows through the existing
  WebSocket path to the store. The Power Delivery card now shows "Not
  connected" when the PZEM is absent instead of misleading zeros. pyserial
  added to requirements.txt. Settings: PZEM_SERIAL_PORT, PZEM_SERIAL_BAUD,
  PZEM_MODBUS_ADDR in .env — empty port disables the feature entirely.
  CRC16 and register parsing verified against the exact request frame the
  hardware test script used (01 04 00 00 00 0A 70 0D). Not verified
  end-to-end against real hardware (requires physical PZEM).
- patch22 (CURRENT): Single-tenant authentication. When INDUS3D_PASSWORD is
  set in .env, all API routes require authentication (Flask session cookie
  or Authorization: Bearer header). When unset, auth is disabled entirely —
  zero friction, identical behavior to pre-patch22. Login: POST /api/auth/
  login with {password}; rate-limited to 5 attempts per IP per 5 minutes
  (in-memory sliding window); password checked with hmac.compare_digest.
  Flask session secret auto-generated on first run and persisted to
  backend/.flask_secret_key. CORS updated: supports_credentials=True with
  origin reflection (required for session cookies cross-origin). Frontend:
  window.fetch patched globally with credentials:'include' in main.jsx.
  New LoginScreen.jsx renders when auth is required and not authenticated,
  respects all 4 themes. Logout button added to SettingsModal. Store gains
  authStatus/fetchAuthStatus/login/logout. App.jsx gates telemetry init
  behind auth check — no WebSocket/API calls fire until authenticated.
- patch23: Setup/install guide (docs/SETUP.md). Comprehensive onboarding
  document covering prerequisites (Pi, Klipper, Moonraker), venv setup,
  .env configuration, frontend build, systemd service, nginx reverse proxy,
  updating, troubleshooting (port conflicts, WebSocket, PZEM, auth lockout),
  architecture diagram, and file structure reference.
- patch24: Disk space monitoring. New `services/disk_monitor.py` polls
  `shutil.disk_usage()` every 60s (configurable), sets warn/critical flags
  when free space drops below configurable thresholds (default: warn < 2GB,
  critical < 0.5GB). Wired into telemetry_worker.latest["disk"], flows
  through WebSocket to the store. Disk alerts fire regardless of print state
  (like thermal runaway) since low disk affects logging/timelapses. Settings:
  DISK_WARN_GB, DISK_CRITICAL_GB, DISK_CHECK_PATH, DISK_CHECK_INTERVAL_S.
  No new dependencies (shutil is stdlib).
- patch25: Database migration system. New `db/migrator.py` scans
  `db/migrations/` for numbered Python scripts (NNN_description.py), runs
  pending ones in order on startup (after init_db()). Schema version tracked
  in a `schema_version` table. Forward-only (no rollback). Exits on failure
  rather than running with a half-migrated schema. Two initial migrations:
  001_baseline.py (establishes version 1, no changes), 002_add_power_columns
  (adds power_voltage/current/watts/energy/frequency/factor columns to
  twin_snapshots for PZEM recording during prints). Verified idempotent.

- patch26: Structured Logging & Frontend Crash Fix.
  Fixed a React crash bug ("blank screen after briefly flashing") where
  the `fetch` override in `main.jsx` improperly destructured `Request`
  objects, causing unhandled promise rejections on initial Suspense renders
  (e.g., from Three.js loading).
  Replaced all `print()` statements in the backend with standard `logging`.
  Added `core/logger.py` which configures a rotating file handler
  (`logs/indus3d.log`, 5MB max, 3 backups) and console output, solving
  production checklist item 26.
- patch27: Safety-Critical Pytest Suite.
  Added a test suite under `backend/tests/` focusing on safety-critical digital twin models and alert systems:
  - `test_thermal_model.py`: Verifies thermal runaway detection logic (both bed and hotend) and ensures low PWM states do not false-positive.
  - `test_quality_controller.py`: Validates M221 flow corrections, deadband adherence, and M220 speed-lag feedback logic.
  - `test_alert_actions.py`: Tests the execution of G-code actions, alert deduplication, and the physical smart-plug power cutoff logic.
  - `test_auth.py`: Ensures rate-limiting and session password verification functions correctly.
  - `test_extrusion_model.py`: Checks under/over extrusion flag detection.
  Tests can be run via `cd backend && .venv/bin/python -m pytest tests/`.
- patch28: CI/CD Pipeline (Zero-Compile).
  - Added `.github/workflows/ci.yml` for linting (`flake8`), security scanning (`bandit`, `npm audit`), and testing.
  - Added `.github/workflows/release.yml` for zero-compile deployment via GitHub Releases.
  - Added `indus3d.cfg` Klipper configuration file for Moonraker `[update_manager]`.
- patch29: Tiered Rate Limiting.
  - Replaced login-only rate limiter with a global, sliding-window rate limiter in `backend/api/rate_limiter.py`.
  - Categories: `login` (5/5m), `hardware_cmd` (10/1m), `default` (120/1m).
  - Fail2Ban style blacklisting (24-hour ban for 3 limit violations).
  - Frontend intercepts HTTP 429 and gracefully shows an animated "Connection Throttled" badge via `App.jsx`.
- patch30: API Versioning & Swagger Docs.
  - Prefixed all endpoints and websockets with `/api/v1/`.
  - Installed `flasgger` to auto-generate Swagger OpenAPI documentation at `/api/docs/`.
  - Added a deprecation header middleware hook in `server.py` for future v2 transitions.
- patch31: Installation Scripts.
  - Added `install.sh` to automate system dependencies, venv creation, Moonraker update_manager config injection, and systemd service creation.
  - Added `uninstall.sh` to safely remove the systemd service and clean up `printer.cfg`.
- patch32: Print Analytics & Gamification.
  - Track `print_time_seconds`, `filament_used_g`, `power_used_wh`, and `cost_usd` per print in the `print_history` SQLite table.
  - `TelemetryWorker` now detects `printing -> complete` transitions, calculates the delta in extrusion and power consumption, and writes it to DB.
  - New API endpoint `/api/v1/twin/stats/lifetime` aggregates total print hours, success rate, and lifetime power/filament consumption.
  - Frontend: `LifetimeStatsCard` added to the `DashboardGrid` to beautifully render these metrics (similar to SimplyPrint's gamification features).
- patch33: Ecosystem & Push Notifications.
  - Implemented an internal notification queue in `core/notifications.py` that streams alerts to the UI over WebSocket.
  - Added HTML5 Web Push (`Notification` API) and a React `ToastContainer` in `App.jsx` to show desktop and in-app alerts for completed prints, failures, or systemic errors.
  - Added `GlobalDropZone` in `App.jsx`: you can now drag-and-drop a `.gcode` or `.bgcode` file anywhere onto the browser window to instantly upload and optionally start printing.
- patch34: Drag-and-Drop Customizable Dashboard.
  - Installed `react-grid-layout` v2.
  - Replaced the static CSS grid in `DashboardGrid.jsx` with a fully responsive, drag-and-drop widget layout.
  - Added a "Lock/Unlock Dashboard" button to toggle editing mode (with edit handles and green outlines).
  - Configured 3 breakpoints (`lg`, `md`, `sm`) to gracefully collapse cards on smaller displays.
  - User layouts are automatically persisted to `localStorage` (`indus3d_layout`).
- patch35: True 3D Digital Twin Visualizer.
  - Implemented `TrueTwin.jsx` using `Three.js` and `@react-three/fiber`.
  - Maps real-time Klipper telemetry coordinates directly into a 3D orbital-camera space.
  - Thermal Raytracing: The nozzle tip glows blue when cold, smoothly fading into a bright emissive red at 250°C.
  - Trajectory Trail: Draws a live geometric 3D trail behind the toolhead while printing.
  - Added alongside the original 2D `Viewport` for side-by-side comparison in the default layout.
- patch36: Macros & Mainsail-Style Settings.
  - Backend: Added `GET /api/v1/printer/macros` which proxies to Moonraker's object list to dynamically fetch all available Klipper `gcode_macro`s.
  - Frontend: Built `<MacrosCard>` widget in the Dashboard that displays a grid of buttons for all non-hidden (no `_` prefix) macros.
  - Frontend: Completely overhauled `<SettingsModal>` to mirror Mainsail's tabbed sidebar layout (Interface, Machine, Webcams, Presets, Notifications).
- patch37: Modal Themes & Layout Reset.
  - Rolled the \`react-grid-layout\` localStorage key to \`indus3d_layout_v2\` to force a one-time layout reset for all clients, ensuring the new TrueTwin and Macros widgets are sized correctly by default.
  - Rewrote \`HeightmapModal\` and \`ConfigEditor\` to use the dynamic theme tokens (\`t.panel\`, \`t.border\`, \`t.heading\`) and brutalist styling logic.
  - Converted the legacy modals to full-screen responsive layouts (\`fixed inset-0\`) to provide an immersive IDE-style experience for editing config files and viewing 3D heightmaps.
- patch38: Hardcoded Legacy Theme Migration & Layout Reset.
  - Rolled the `react-grid-layout` localStorage key to `indus3d_layout_v3` to enforce a hard layout reset because the v2 reset was superseded. This permanently fixes the TrueTwin and Macros widgets being trapped in 1x1 default boxes.
  - Identified that `PrintStatusCard.jsx`, `QualityPanel.jsx`, `ActionLog.jsx`, and `CameraFeeds.jsx` were still utilizing hard-coded dark mode CSS classes instead of the new unified theming engine.
  - Rewrote all four missing widget components to utilize `useThemeTokens()` and `useIsBrutalist()` (`t.panel`, `t.heading`), seamlessly aligning them with the Classic, Workshop (Brutalist), Blueprint, and Creme themes.
- patch39: Deep Theming for Legacy Modals.
  - While the outer layout of the Surface Topography and Config Editor modals was themed in Patch 37, the inner 3D canvas and text editor inputs were still hardcoded to dark colors (`#1e1e1e`, `black`).
  - Rewrote the `<Canvas>` background and `<textarea>` components in `Modals.jsx` to dynamically switch their background colors, text colors, and canvas clear colors based on the active theme (e.g., `#FFE9A8` and `#111` text for the Brutalist text editor).
- patch40: Theme-Specific Console Palettes & App Recovery.
  - Recoded `DashboardGrid.jsx` to dynamically switch the G-Code Console interior window colors based on the active theme:
    - Creme: Cream (`#F5F0E8`) background with emerald green text.
    - Blueprint: Light blue (`#d0e3ff`) background with black text.
    - Workshop: Bone white (`#FDFBF7`) background with black text.
    - Classic: Default dark/gray palette.
  - Bumped the grid layout cache to `v4` to ensure any broken states from hot-reloads are wiped clean.
- patch41: MacrosCard Null Safety Fix.
  - Added null safety checks for the `macros` array inside `MacrosCard` (`(macros || []).filter(...)`). This fixes a critical rendering crash that occurred immediately after app startup if the Klipper Moonraker `/printer/objects/list` API took too long to return the list of macros (leaving the state uninitialized).
- patch42: Digital Twin Responsive Grid Layout.
  - Rebuilt the `DigitalTwinPage` to use `react-grid-layout` just like the main dashboard.
  - Extracted inline data panels (Kinematic Model, Lifetime Odometry, Thermal Model, Extrusion Model) into discrete React components to support grid wrapping.
  - Added the "Lock / Unlock Dashboard" button and customizable layout persistence (cache key `indus3d_twin_layout_v1`). Users can now fully drag, drop, and resize the deep-dive analytics cards.
- patch43: Console Theme Store Typo Fix.
  - Corrected a bug where the `Terminal` component was attempting to read `useStore((s) => s.uiTheme)` instead of the correct property `s.theme`. This caused the newly implemented theme-specific interior console colors from Patch 40 to silently fail and fall back to the Classic theme colors.
- patch44: Legacy Modals Full Palette Application.
  - Rewrote the color engine for `HeightmapModal` (Surface Topography) and `ConfigEditor` to explicitly map their inner backgrounds, text colors, and sidebar highlights to the active theme's base color.
  - `ConfigEditor` textarea background now precisely matches `#F5F0E8` (Creme), `#d0e3ff` (Blueprint), or `#FDFBF7` (Workshop), with corresponding themed text colors.
  - Replaced hardcoded `bg-gray-500/5` sidebar shades with a more neutral `bg-black/5` to prevent muddy color mixing on pastel themes.
- patch45: Dynamic vs Static Dashboard Modes.
  - Introduced a "Dashboard Mode" toggle in `SettingsModal.jsx` (Interface tab) to switch between Dynamic and Static modes.
  - Dynamic mode uses the advanced Indus3D `react-grid-layout` with `TrueTwin` and `QualityPanel`.
  - Static mode hides the advanced corrective features and falls back to a clean, Mainsail/Fluidd-like layout preset (`DEFAULT_STATIC_LAYOUTS`) for users who want traditional Klipper telemetry only.
  - Layout engine independently caches custom dragging/resizing for each mode.
- patch46: SettingsModal Regex Injection Fix.
  - Fixed a regex replacement error that silently failed to inject the Dashboard Mode HTML into the Settings UI tab. The toggle buttons for Dynamic and Static mode are now correctly visible right above the Layout Management section.
- patch47: Settings Mode Labels and About Tab.
  - Refined the "Dashboard Mode" toggle buttons in Settings to simply read "Dynamic" and "Static".
  - Rewrote the helper text below the toggle to clearly explain the difference without referencing Mainsail by name.
  - Added an "About" tab to the Settings menu with an instructional guide on how to best utilize Indus3D's features (unlocking the dashboard, themes, TrueTwin).
- patch48: Dashboard Static Mode Crash Fix.
  - Fixed a React render crash that occurred when switching between Static and Dynamic modes. The layout arrays in the grid layout engine were getting out of sync with the conditionally rendered React children, throwing a grid mismatch error.
- patch49: Settings Reactive State Fix.
  - Fixed a UI bug where the Dashboard Mode toggle buttons in Settings did not visually update when clicked until the component was re-rendered.
  - Changed `useStore.getState().dashboardMode` to a reactive `useStore((s) => s.dashboardMode)` hook so the button active state highlights immediately upon click.
- patch50: Dashboard Layout Corruption Fix.
  - Resolved an issue where toggling between Dynamic and Static modes caused `react-grid-layout` to cache overlapping coordinate maps (like `TrueTwin` covering the entire screen).
  - Wiped the corrupted layouts by bumping the local storage cache keys to `indus3d_layout_v5` and `indus3d_layout_static_v2`.
  - Updated the Settings "Reset Grid Layout" button to correctly clear both of the new versioned cache keys.
- patch51: Unified Layout Preservation.
  - Eliminated the two-tier layout system. Switching between Dynamic and Static modes no longer jumps to a separate cached layout.
  - Wrote a custom `onLayoutChange` merger function that ensures widgets hidden in Static mode are preserved in the internal layout array.
  - When switching to Static mode, the grid seamlessly compacts. When returning to Dynamic mode, the advanced widgets slide back into their exact original coordinates.
- patch52: Settings Tab Layout Shift Fix.
  - Fixed a UI jitter bug where clicking left sidebar tabs in the Settings modal caused the tab sizes to slightly change (due to adding a 2px border on the active state). 
  - Added a `border-2 border-transparent` placeholder to inactive tabs to stabilize their dimensions.
- patch53: Layout Compaction Bug Fix.
  - Reverted to the isolated Dual Layout system (separating `indus3d_layout_dynamic` and `indus3d_layout_static`) to prevent `react-grid-layout` from shifting, compacting, or colliding the `TrueTwin` canvas when it is unmounted and remounted during a toggle.
  - Kept the synchronous state render override (Patch 50) so the grid instantly boots up with the exact saved coordinates without passing through a broken intermediate state.
- patch54: Flawless Option B Layout Compaction.
  - Resolved the "infinite collision loop" bug where `TrueTwin` would get pushed further down the screen (and resized/squished) every time the user toggled the mode.
  - Achieved this by initializing the `Static` mode layout using a strictly filtered clone of the active `Dynamic` mode layout, and allowing the layout engine to natively compact it. 
  - This perfectly preserves TrueTwin's original coordinates in the Dynamic vault while granting the user completely seamless upward compaction in Static mode.
- patch55: React Render Crash Fix.
  - Eliminated the synchronous state-derivation loop in `DashboardGrid` that was throwing a React "Maximum update depth exceeded" / update function crash.
  - Moved the `key={dashboardMode}` override directly to the parent `<DashboardGrid>` component within `App.jsx`, guaranteeing clean and fully isolated component remounts upon toggling modes without breaking React Hook rules.
- patch56: App.jsx ReferenceError Fix.
  - Fixed a `ReferenceError` where `dashboardMode` was used as a component `key` but wasn't correctly imported into the `App.jsx` scope, causing the crash to persist.
- patch57: Grid Render & Loop Safety Nets.
  - Wrapped `DashboardGrid` in a render-phase `try/catch` to isolate and expose exact error messages instead of generic boundary failures.
  - Injected a deep-equality `JSON.stringify` check in `onLayoutChange` to prevent React 18 strict-mode infinite update loops ("Maximum update depth exceeded") caused by `react-grid-layout` re-triggering layout calculations on component unmount/remount boundaries.
  - Hardened `MacrosCard` to gracefully ignore malformed non-string macro data.
- patch58: The True Root Cause (ReferenceError Fix).
  - The previous custom `try-catch` successfully isolated the exact error: `CardWrapper is not defined`.
  - Discovered that an aggressive regex replacement in Patch 54 accidentally swallowed the `CardWrapper` component definition, causing a hard `ReferenceError` on every dashboard render.
  - Restored `CardWrapper` to `DashboardGrid.jsx`. The dashboard now transitions between layouts flawlessly.
- patch59: Modal Positioning Fix.
  - Changed `ConfigEditor` and `HeightmapModal` (Surface Topography) to use `absolute inset-0` instead of `fixed inset-0`. This ensures they render cleanly inside the main workspace container rather than hijacking the entire browser viewport, allowing the global sidebar to remain visible and fully functional underneath.
- patch60: Print Analytics & Gamification.
  - Upgraded `AnalyticsCard` on the Digital Twin page to display a rich SVG donut chart showing the Print Success/Failure ratio, alongside summary statistics.
  - Upgraded `MaintenancePanel` to display visual Maintenance Health progress bars for each critical metric (odometer distance, thermal cycles, stress scores) instead of just plain text hints.
  - Modified the backend simulation and API `GET /api/v1/maintenance` to expose quantitative maintenance thresholds and current values.
- patch61: Fleet Management & Mobile Polish.
  - Added a new `Fleet Command` tab to the global navigation rail.
  - Implemented `FleetPage.jsx` which displays a responsive `Multi-Printer Grid`.
  - The grid shows the actual live printer alongside multiple simulated instances to demonstrate fleet capability.
  - Added a `Mobile-First "Quick View"` full-screen modal feature to each printer card. Tapping the expand icon opens a transparent overlay of stats on top of a full-screen webcam feed, ideal for quick phone checks.
- patch62: Smart Timeline & Playback.
  - HOTFIX: Fixed ReferenceError in App.jsx when attempting to render IncidentModal by correctly importing `telemetry` and `dismissedIncident` state.

  - Added a global `IncidentModal.jsx` (Root-Cause UI) that automatically interrupts the user when the printer halts or fails, displaying the exact critical alert that triggered the shutdown.
  - Added a "View Incident Playback" button to the modal which automatically switches to the Digital Twin tab and begins a 3D G-code replay of the failure.
  - Upgraded the backend `timelapse` service. If a print halts/fails, it automatically splices the final 10 seconds of webcam snapshots into an `incident.mp4` video clip.
  - Also added the `0.05mm` step interval to the `ToolheadControls` per user request.
  - Completely re-wired the `MaintenancePanel` on the frontend to fetch real data via a new `/api/v1/maintenance/reset` endpoint, complete with interactive "Reset Task" buttons.
  - Architected a new `plugins/` framework in the backend allowing custom Python scripts to dynamically register Flask API routes without touching core code.
  - Added a lightweight `spoolman_client` and hooked it into the print_history logger to calculate true print cost (Filament + $0.15/kWh electricity estimation).
- patch64: TrueTwin Simulator Aliasing Fix
  - Fixed an aliasing issue in the Digital Twin caused by the simulator time-warping 20 waypoints per 10Hz tick. The physical toolhead trail was drawing jagged, straight lines ("garbage") across the interior of the Benchy contour. Suppressed the live green trail renderer in `simMode`, allowing the full-resolution grey G-code toolpath to display perfectly.

- patch65: Visualizer Stabilization & Terminal Upgrades
  - Fixed a critical React suspense crash (blank white screen) in the `Viewport` component caused by an un-suspended `@react-three/drei` `<Environment>` HDRI loader.
  - Fixed a silent bug in `GCodeVisualizerV2` where returning `null` on initial mount permanently prevented the native Three.js buffer geometry from initializing.
  - Re-mapped terminal text colors in Simulator mode. Manual `>>> ` commands now display in User Blue, system `[INDUS]` commands in System Orange, the active executing line in Green, and all standard file G-code in default gray text.
  - Implemented command history in the `Terminal` component using `ArrowUp` and `ArrowDown`, including draft preservation for newly typed commands.
  - Upgraded the "Cancel Object" functionality in `GCodeVisualizerV2`. The 3D toolpath now freezes exactly at the byte it was cancelled (leaving printed plastic on the bed) instead of deleting the object entirely.

### How to start a new chat
Paste the contents of this file as the FIRST message.
Recommended opener:
  "I'm continuing development of the Indus3D project. Here is the complete
   context document — please read it carefully before we begin:
   [paste this file]"

The new chat will have full architectural knowledge, know what patches have been
applied, know what's broken, know what's validated, and can continue immediately
without re-explanation.

## patch66: Pressure Advance Calibration Wizard & Profile Sync
- **PA Test Pattern Generator:** Added `_pa_test_gcode()` to `backend/api/server.py` that generates a Klipper-compatible slow→fast→slow test pattern, sweeping `SET_PRESSURE_ADVANCE ADVANCE=<k>` across a user-configurable range (default 0.0–0.1, step 0.005). Each line prints at a different K value so the user can visually identify the cleanest speed transitions.
- **PA API Endpoint:** Added `POST /api/v1/calibration/pa-test` that generates the G-code and uploads it to Moonraker (or returns it in sim mode). Also added `apply_pa` step to the calibration runner for one-click `SET_PRESSURE_ADVANCE` application.
- **CalibrationWizard UI:** Rewrote `CalibrationWizard.jsx` to include a full "Pressure Advance tuning" section with configurable Start K / End K / Step inputs, a "Generate & Upload" button, and an "Apply result" panel where the user enters the best K and applies it live.
- **Input Shaping:** Added `input_shaping` step dispatching `SHAPER_CALIBRATE` to the calibration wizard.
- **Server-Side Profile Sync:** Created `user_preferences` table in SQLite. Added `GET/POST /api/v1/profile/preferences` endpoints. Modified `store.js` to sync theme/mode/dark preferences to the backend on change, and fetch them on app load.
- **Power Control:** Added E-STOP button to TopHeader, PowerModal with Restart/Firmware Restart/Reboot/Shutdown actions, and backend routes proxying to Moonraker's machine control API. Simulator now handles M112/RESTART natively.

## patch67: Automated Annotated G-Code PDF Reports
- **Backend Environment:** Added `reportlab` dependency for PDF rendering.
- **Database Schema:** Added `annotated_gcode_path` column to `print_history` table (migration 005).
- **PDF Generator:** Created `backend/services/gcode_annotator.py` which uses `reportlab` to render a clean, color-coded PDF of the G-code file with a legend on page 1 (showing Slicer, Indus3D QC, Indus3D Critical, User, and Comment line colors).
- **Automation Hook:** Updated `backend/services/qa_reporter.py` to automatically trigger `generate_annotated_gcode_pdf` alongside the QA telemetry report when a print finishes.
- **Simulator & API:** Updated `backend/workers/simulator.py` and `backend/api/server.py` to ensure both report paths are passed to the frontend in the `/api/v1/twin/history` endpoint.
- **Frontend UI:** Added a second download button (green FileDown icon) next to the existing QA report button in the Digital Twin / Fleet Command page for easy one-click download of the annotated G-code PDF for research.

## patch68: Virtual Spool Manager
- **Database Schema:** Created migration 006 to add a `spools` table (`name`, `material`, `color`, `starting_weight`, `used_weight`, `is_active`).
- **Telemetry Integration:** Updated `backend/digital_twin/kinematic_model.py` (`_persist_odometry`) and `simulator.py` to automatically calculate extruded mass (based on 1.75mm filament volume) and deduct it from the active virtual spool in real-time.
- **Backend API:** Added CRUD endpoints at `/api/v1/spools` to list, create, delete, and set active spools.
- **Frontend UI:** Created a new `SpoolManager.jsx` modal (accessible via the new Database icon in the NavRail) to visually track remaining filament with progress bars and manage the spool inventory.

## patch69: Local Touch UI Implementation
- **React Frontend Integration:** Built the `TouchUI` component directly into the Vite React app instead of creating a separate project. The app checks for `?mode=touch` in the URL to render the touch-optimized dashboard.
- **Controls & Filament Tab:** Added fully functional XY/Z jogging, XYZ homing, and Extrude/Retract buttons. 
- **Backend API Updates:** Modified the `/api/v1/control/jog` endpoint in `backend/api/server.py` to support Extruder (`e`) axis commands, and increased the single-move limit to `±100mm` to allow loading and unloading filament.
- **Simulator Updates:** Ensured `simulator.py` accepts and processes the new `e` jog argument.

## patch70: Rust Vibration DSP Pipeline (Phase 1)
- **Rust Engine:** Initialized the `indus3d-dsp` Cargo project in `backend/dsp/`.
- **Signal Processing:** Implemented `dsp.rs` using `rustfft` to compute Peak Frequency (Hz), Magnitude, RMS, and Kurtosis (shock/impact detection).
- **Network Pipeline:** Wrote `main.rs` to ingest continuous 3200Hz ADXL data via a low-overhead UDP socket (`127.0.0.1:3200`), buffer it into 1-second sliding windows with 50% overlap, and stream the aggregated metrics back to Python as JSON over UDP.

## patch71: Rust Vibration DSP Pipeline (Phase 2 - Klipper Integration)
- **Klipper Extra Module:** Wrote a custom Klipper Python extension (`klipper_modules/indus_vibration.py`) that hooks into Klipper's bulk sensor data pipeline.
- **True Continuous Streaming:** The module introduces `INDUS_VIBRATION_START` and `INDUS_VIBRATION_STOP` G-code commands. When started, it intercepts the ADXL345 3200Hz datastream directly from the Klipper multiplexer and blasts it as raw, non-blocking UDP packets to `127.0.0.1:3200`.
- **Zero-Overhead:** Bypasses disk I/O completely, allowing real-time telemetry streaming from the EBB36 toolboard without causing "Timer too close" errors or lagging the Klipper Python runtime.

## patch72: Configurable Mathematical Models for Dynamic Parameters
- **Modular Math Functions:** Created `backend/digital_twin/control_models.py` to isolate the equations for Pressure Advance (shear-thinning), Hotend Temperature (feedforward heating), Part Cooling, Acceleration Damping, and Z-Offset (thermal expansion). This ensures the pure math can be easily tuned or modified based on real-world tests without digging through the controller logic.
- **Controller Integration:** Wired these models into `backend/digital_twin/quality_controller.py`'s `update()` loop. The controller now dynamically issues `SET_PRESSURE_ADVANCE`, `M104`, `M106`, and `SET_GCODE_OFFSET` based on real-time telemetry (flow rate, thermal state) processed through these math models.

## patch73: Dynamic Velocity and Square Corner Velocity (Jerk) 
- **Velocity Limit (`SET_VELOCITY_LIMIT VELOCITY=...`):** Added a math model to throttle max velocity as a function of the hotend's absolute volumetric flow limit, with exponential decay at high Z-heights to prevent frame wobble on tall/slender prints.
- **Square Corner Velocity (`SQUARE_CORNER_VELOCITY=...`):** Added a math model to dynamically dampen cornering impulses (Jerk) when the DSP vibration engine detects high-amplitude ringing or structural resonance.
- **Integration:** Integrated both into `control_models.py` and `quality_controller.py`.

## patch74: Mathematical Models from Research Papers (Areas 1-4)
- **Extracted Equations:** Processed 57 research papers to extract and implement state-of-the-art additive manufacturing models into `control_models.py`.
- **Area 1 (Curved Toolpath Over-Extrusion):** Added trigonometric dampening to flow rate `a * cos(θ)` to prevent bulging on tight inner radii.
- **Area 2 (Thermal Lag & Droplet Coalescence):** Added a first-order thermal lag predictor and the Frenkel-Bellehumeur coalescence rate equation. Integrates with the controller to boost temperature by 2°C or slash fan speed if inter-layer bonding is at risk.
- **Area 3 (Structural Dynamics DSP):** Added structural stiffness `K = M * (2πf)²` and torque ripple estimation to the Rust `indus3d-dsp` module, updating the UDP JSON payload serialization to include these new fields.
- **Area 4 (Physical-to-Virtual Mapping):** Added a linear coordinate transformation matrix to `simulator.py` to map raw mechanical coordinates to the digital twin's normalized virtual space.

## patch75: Codebase Bugfixes and Kinematic Motion Control Models
- **Critical Fixes:** Resolved an orphaned `_dynamic_params` method bug in `quality_controller.py`, fixed a corrupted literal `\n` import in `telemetry_worker.py`, and corrected 6 snake_case vs camelCase key mismatches in the snap dictionary that were preventing models from accessing live telemetry.
- **Kinematic Group A & B (Segment & Geometry):** Added math for calculating precise analytical bead width, stadium-shaped bead cross-section, actual filament nozzle exit velocity, and dynamic segment traversal distances from raw coordinates.
- **Kinematic Group C (Zero-Jerk Motion):** Added a sinusoidal distance-to-speed scaling constraint to cap velocity on micro-segments and prevent impossible acceleration demands.
- **Kinematic Group D & E (Closed-Loop PI Control):** Upgraded `quality_controller.py` by adding Integral error accumulators (`PI` control) for temperature tracking, and an automated layer-to-layer closed-loop Z-offset correction based on tracking `live_z` versus nominal layer height.

## patch76: Indus3D Lab Operations (QA, Vision, and Autonomous Throttling)
- **Computer Vision (YOLOv8):** Completed the dormant `backend/edge/inspector.py`, enabling offline YOLOv8n object detection (Spaghetti, Warping, Blob). Wired it to intercept the live camera feed and push visual defects directly into the telemetry stream.
- **Closed-Loop QA Verification:** Upgraded the `QAReporter` (`backend/services/qa_reporter.py`) to cross-reference final dimensions against an AS9100 standard CAD specification JSON. Automatically flags Out of Tolerance (OOT) parts.
- **Jobs & Work Orders:** Integrated a lightweight job queue in `backend/workers/job_queue.py` to support Lab operations (Jobs as Work Orders) rather than just single prints.
- **Config Versioning:** Added SQLite-backed config history to track changes over time.
- **Autonomous Stress Mitigation:** Upgraded `quality_controller.py` to actively throttle Square Corner Velocity (SCV) and Acceleration (`SET_VELOCITY_LIMIT`) via closed-loop math models in `control_models.py` when the digital twin's `stress_score` detects mechanical fatigue.
- **Bugfix (Sim Mode Visualizer):** Fixed an issue in `simulator.py` where `multi_benchy` requests in sim mode were incorrectly hardcoded to load the monolithic single `3dbenchy` file, breaking the frontend G-code viewport visualization of the toolpath array.
