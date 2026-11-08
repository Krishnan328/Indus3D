# Indus3D — Development Reference & Benchy Test Guide

## What Indus3D Actually Does (Quantitative)

This document describes every active feature, what it measures, what it corrects,
and what you should expect to see in a real print comparison test.

---

## 1. Extrusion Flow Control (M221)

**What it measures:**
- Commanded E-axis delta per tick → volumetric flow (mm³/s)
- Expected flow from velocity × bead cross-section geometry
- Flow ratio = actual_volumetric / expected_volumetric

**Honest scope:**
- Detects: slicer E-value misconfiguration, dramatic stepper skip events
- Cannot detect: partial clogs, filament grinding, viscosity changes from moisture
  (these cause real under-extrusion but the commanded E position remains correct)
- The flow ratio is a slicer consistency check, not a direct measurement of deposited material

**When it activates:**
- Only during `print_state == "printing"` AND velocity > 10 mm/s
- Deadband: ±4% flow ratio deviation before any correction fires
- Correction interval: minimum 8 seconds between M221 commands

**What it sends:**
```
M221 S{value}   (clamped 85–115%)
```

**Expected benchy result:**
- If your slicer flow is already calibrated: no corrections fire, flow ratio stays 0.95–1.05
- If your slicer has a 10% flow error: M221 correction fires within the first 30 seconds
- Dimensional accuracy improvement: 0–5% on wall thickness (only if slicer was miscalibrated)

**What to measure:**
- Wall thickness of benchy hull with calipers (target: your line width setting)
- Surface finish — over-extruded surfaces show ridges between lines

---

## 2. Speed-Lag Feedback (M220)

**What it measures:**
- Positional lag: `lag = sqrt((cmd_x - live_x)² + (cmd_y - live_y)² + (cmd_z - live_z)²)`
- Klipper exposes both commanded position (from G-code) and live position (motion planner)
- Lag magnitude > 0.3mm threshold triggers speed reduction

**What it corrects:**
```
M220 S{value}   (reduces to 50–100% of programmed speed)
Restores at: +2% per 3-second interval when lag clears
```

**When it activates:**
- Only during active printing
- Correction interval: minimum 3 seconds between M220 commands

**Expected benchy result:**
- On well-tuned printers at conservative speeds: M220 never fires (lag stays < 0.3mm)
- At aggressive speeds or with belt tension issues: M220 fires during fast infill moves,
  reducing speed until lag clears, then restoring gradually
- Ringing reduction: indirect — by preventing the printer from exceeding its servo
  following capability, corner ringing from commanded-vs-actual velocity mismatch is reduced

**What to measure:**
- Benchy bow detail sharpness (ringing artifact indicator)
- Compare bow and stern corner quality with and without Indus3D

---

## 3. Variable Input Shaping (SET_INPUT_SHAPER)

**Status: Requires calibration before it activates**

**Setup required:**
1. Run `SHAPER_CALIBRATE AXIS=Y` on an empty bed, note the Y resonance frequency
2. Weigh your heated bed assembly (aluminium plate + glass/PEI + carriage, not including filament)
3. Set in `backend/config/indus_overrides.cfg`:
   ```ini
   y_resonance_hz = 35.2   # your measured value
   bed_mass_g     = 1450   # your measured value
   y_shaper_type  = mzv    # your chosen shaper type
   ```

**What it does:**
```
f_new = f_baseline × √(m_baseline / m_total)
where: m_total = m_baseline + (filament_consumed_mm × π × (dia/2)² × density_g_cm3 / 1000)
Sends: SET_INPUT_SHAPER SHAPER_FREQ_Y={f_new} every 30 seconds
```

**Expected correction magnitude:**
- For a 300g benchy on a 1500g bed: ~9% frequency shift (35Hz → 31.9Hz)
- MZV shaper tolerates ~15% frequency error before ringing exceeds 5%
- Correction is likely only visible on large heavy prints (>400g) or printers
  with low baseline resonance frequency (<25Hz)

**Validation experiment:**
- Print Klipper's resonance test pattern at 0%, 50%, and 100% of print height
- Photograph and compare ringing amplitude at each height
- If amplitude does not change, shaper correction has no measurable benefit

---

## 4. Thermal Shadow PID

**What it measures:**
- Runs identical PID math using kP/kI/kD from printer.cfg
- Compares shadow PWM output to actual Klipper heater PWM
- `pid_delta = |shadow_output - actual_pwm|`

**What it detects:**
- pid_delta > 0.05 sustained over 30 seconds: heater or thermistor anomaly
- Thermal runaway: heater PWM > 80% sustained while temperature drops > 15°C in 5 seconds

**Current limitations:**
- pid_delta varies legitimately with ambient temperature changes
- No failure data yet to validate specific threshold values
- Consider this a monitoring feature, not a calibrated diagnostic

---

## 5. Lifetime Odometry and Maintenance Alerts

**What it tracks:**
- Cumulative X, Y, Z, E axis travel in metres (persisted to SQLite, survives restarts)
- Direction reversal count per axis → stress score accumulator
- Heat cycles per heater (cold→hot→cold transitions)

**Alert thresholds (configurable in indus_overrides.cfg):**
```
X/Y odometry > 500m   → "Lubricate axis"
Z odometry   > 200m   → "Lubricate lead screw"
Heat cycles  > 300    → "Inspect heater cartridge"
Stress score > 0.3    → "Check belt tension"
```

**Note on odometry accuracy:**
- A 0.05mm deadband filters float noise from the position feed
- Values reset if DB is deleted; zero the DB after installing

---

## Benchy Test Protocol

### Setup
1. Use identical slicer settings for both prints (same file)
2. Same filament roll, same temperature, same bed
3. Print #1: Klipper only (no Indus3D backend running)
4. Print #2: Klipper + Indus3D running with quality controller active

### Measurements to take
| Measurement | Tool | Expected difference |
|---|---|---|
| Bow wall thickness | Calipers | 0–3% if slicer flow was off |
| Chimney diameter | Calipers | < 1% |
| Bench top surface roughness | Visual + photo | Possible improvement if speed was corrected |
| Ringing at bow | Photo, oblique light | Only visible if M220 fired during print |
| Time to print | Timer | May be longer if M220 reduced speed |

### Honest expectations
- If your printer is already well-calibrated: minimal measurable difference
- The value of Indus3D for a well-calibrated printer is monitoring and maintenance,
  not immediate print quality improvement
- Quality improvement is most visible when the printer has drift (worn belts,
  degraded heater, slicer misconfiguration)

### What to log during the Indus3D print
- Screenshot of QualityPanel showing corrections timeline
- Note if any M221 or M220 commands fired (and at what values)
- Note if any alerts fired and when
- Export twin_snapshots table after print for analysis

## Sim Mode Benchy Data

`python main.py --sim` (default shape) no longer draws a hardcoded sine-wave
hull approximation. `workers/data/benchy_contours.json` is baked offline from
a real 3DBenchy.stl: 120 Z-height cross-sections of the actual mesh, each
simplified to ~0.15mm tolerance (Shapely `.simplify()`), centered on the bed,
and stored as plain `[x, y]` contour point lists — no `trimesh`/`numpy-stl`
dependency at runtime, so nothing extra is needed on the Pi.

`workers/gcode_shapes.py`'s `_benchy_moves()` reads that file directly. The
`--layers` flag now means "how many of the 120 baked slices to use" (evenly
subsampled), not a literal physical layer count — real geometry doesn't have
a meaningful "simpler shape" mode:

| `--layers` | Waypoints | Approx. sim duration @ WAYPOINTS_PER_TICK=5 |
|---|---|---|
| 30  | ~1,640 | ~33s (default before this change) |
| 60  | ~3,076 | ~62s (current default) |
| 120 (max, full detail) | ~6,070 | ~121s |

If `benchy_contours.json` is ever missing, `_benchy_moves()` falls back to
the old procedural sine-wave hull rather than crashing — it'll look wrong
(the lens/eye shape, not a boat) but sim mode will still run.

**Regenerating it** (e.g. against a different STL, or a different
simplification tolerance): `tools/precompute_benchy_contours.py` takes a
path to any watertight-ish STL and rewrites the JSON. Requires `trimesh` +
`shapely` — dev-machine only, never needed on the Pi:
```bash
pip install trimesh shapely --break-system-packages
python tools/precompute_benchy_contours.py path/to/3DBenchy.stl
```

## Spoolman Setup (optional)

The spool picker in `PrintStatusCard` needs Moonraker's `[spoolman]`
component pointed at a running [Spoolman](https://github.com/Donkie/Spoolman)
instance. Indus3D doesn't run or bundle Spoolman itself — it's a separate
self-hosted service, same as it is for Mainsail/Fluidd.

```ini
# moonraker.conf
[spoolman]
server: http://<spoolman-host>:7912
sync_rate: 5
```

If this section is absent or Spoolman is unreachable, `SpoolPicker` shows a
quiet "not connected" line instead of an error — nothing else in Indus3D
depends on it. Once configured, Moonraker reports filament usage to
Spoolman automatically from Klipper's own E-position tracking; Indus3D adds
its own `extrusion_model.py`-computed figure (real volumetric flow, not
just commanded E) alongside it for comparison.

## Thermal Runaway Power Cutoff (optional, off by default)

A detected thermal runaway always sends `M112` (Klipper emergency stop) —
that part is unconditional and was made reliable in this patch: it now
fires from `telemetry_worker.py` directly, every tick, regardless of
whether any browser has the dashboard open. Previously this only fired if
the frontend had derived the alert client-side and called the action
endpoint — a runaway with nobody watching the dashboard would not have
triggered it. That's fixed now, independent of the power-cutoff feature
below.

The power cutoff itself is a separate, **opt-in** layer on top of M112 —
disabled by default. It exists because M112 depends on Klipper/the MCU
still being able to respond. A physically stuck heater MOSFET (the classic
thermal-runaway hardware failure) can keep heating even after Klipper
shuts down; a relay on a separate circuit can still cut it.

**Setup:**
```ini
# moonraker.conf — do NOT set locked_while_printing here, see below
[power printer_psu]
type: gpio
pin: gpio27
```
```ini
# backend/config/indus_overrides.cfg
power_cutoff_enabled = true
power_cutoff_device  = printer_psu
```

**The one mistake that will silently defeat this feature:** if the
`[power printer_psu]` device has `locked_while_printing: True`, Moonraker
refuses on/off requests during a print — which is exactly when a runaway
happens. Indus3D's `PowerPanel` (Digital Twin page) checks for this
mismatch and shows a red warning if it detects it, but it's worth getting
right in moonraker.conf directly rather than relying on the UI catching it.

## Notifications (optional, off by default)

Discord and/or Telegram, configured independently — use either, both, or
neither. Credentials go in `backend/.env`, not through the UI (webhook URLs
and bot tokens are secrets; `SettingsModal` only shows a read-only
connected/not-connected status).

```bash
# backend/.env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
NOTIFY_ON_WARN=false   # true also notifies on lag/under-extrusion/over-extrusion, not just critical
```

Discord: Server Settings → Integrations → Webhooks → New Webhook, copy the URL.
Telegram: message @BotFather to create a bot and get a token, message your
bot once, then check `https://api.telegram.org/bot<TOKEN>/getUpdates` for
your chat_id.

What triggers a notification: print completed, print failed/cancelled, and
any critical alert (thermal runaway) — all fire from `telemetry_worker.py`'s
own loop, same reliability guarantee as the power cutoff above, not
dependent on a browser tab. Warn-level alerts (lag, under/over-extrusion)
are opt-in via `NOTIFY_ON_WARN` — off by default so a well-tuned printer
doesn't spam your phone every time a value briefly crosses a threshold.

Adding a new channel (Pushover, ntfy.sh, Slack, ...): add a `_send_<name>`
function to `core/notifications.py` following the existing two, add it to
`_CHANNELS`, add its config to `settings.py`. Nothing else needs to change.

## Timelapse (optional, off by default)

```ini
# backend/config/indus_overrides.cfg
timelapse_enabled    = true
timelapse_mode       = layer      # or "interval"
timelapse_interval_s = 10         # only used in interval mode
timelapse_fps        = 15
```

Requires `ffmpeg` on the host (`apt install ffmpeg`) — invoked as a
subprocess only, not bundled, and stitching runs in a background thread so
it never blocks the telemetry loop. Two capture modes:

- **`layer`** — snapshots whenever Z increases, using Indus3D's own live Z
  tracking. No slicer-side macros needed (most timelapse tools require
  `SET_PRINT_STATS_INFO CURRENT_LAYER=...` or similar — this doesn't).
- **`interval`** — snapshots every `timelapse_interval_s` seconds while
  printing. Works with literally any gcode, any slicer.

Frame source is Crowsnest's standard `?action=snapshot` endpoint, derived
automatically from your existing webcam URL. If your camera runs in
`camera-streamer` mode, snapshot support can be inconsistent — a failed
capture is logged and skipped, never allowed to interrupt a print.

Start/stop is automatic, tied to the same print-state transition tracking
that drives the completion/failure notifications above — no manual
start/stop needed. Prints with fewer than 2 captured frames (e.g.
cancelled almost immediately) are cleaned up without attempting to stitch.
Completed timelapses appear in the "Timelapse" card on the Digital Twin
page, downloadable from there.

## File Manager

New "Files" page (nav rail, third icon). Browses whatever's already on the
printer's `gcodes` root — separate from the upload button already in
`PrintStatusCard`, which is for sending a new file. Per file: thumbnail (if
the slicer embedded one), size, modified date, estimated print time,
filament weight — all from Moonraker's real metadata endpoint, not
recomputed. Print and delete actions both confirm before acting; delete is
irreversible and there's no undo.

Backend additions, all thin proxies to Moonraker's documented API (verified
against Moonraker's own docs, not guessed):
- `GET /api/printer/files/metadata?filename=` → `GET /server/files/metadata`
- `DELETE /api/printer/files/gcodes/<filename>` → `DELETE /server/files/gcodes/<filename>`
- `POST /api/print/start` → `POST /printer/print/start?filename=` (alongside
  the existing pause/resume/cancel/upload routes already in `server.py`)

Path-traversal protection on the delete route is tested against both plain
(`../../etc/passwd`) and URL-encoded (`..%2f..%2fetc%2fpasswd`) attempts —
plain traversal is actually caught by Werkzeug's own routing before it
reaches the handler at all; the encoded form is what actually needs the
explicit `".." in filename` check, since Flask decodes it before your view
function sees it.

Metadata is fetched per-file on mount, not paginated or lazy-loaded yet —
fine for typical gcode folder sizes, worth revisiting if someone has
hundreds of files sitting on the printer.

## Hardware Efficiency (1GB Pi / Creality mainboard targets)

Three fixes, all measured/verified, not just theorized:

**Batched SQLite writes.** `log_snapshot()` used to open a connection,
INSERT, commit (blocking fsync), close — every tick, on the same thread
that polls Moonraker and runs the quality controller. Now it appends to an
in-memory buffer (measured: 0.054ms per call, down from a blocking
disk-bound call) and a background thread flushes in one batched
`executemany()` every 2 seconds on a persistent connection. Trade-off: the
most recent ~2s of snapshots aren't in the DB yet if you query
`get_recent_snapshots()` mid-window — fine for a look-back replay tool, the
WebSocket firehose already covers "right now." A clean shutdown flushes
via `atexit`; a hard kill can still lose the last ~2s, same risk class as
before.

**Split requirements.** `requirements.txt` is now only what the running
backend actually imports (verified via grep across the whole tree, not
assumed) — Flask, requests, python-dotenv. `requirements-vision.txt` holds
opencv/ultralytics for if `backend/edge/` ever gets wired in, with an
explicit note to run that on a companion device, not the same board.
Dropped `psutil` and `websocket-client` entirely — both were listed for
features that were never built.

**Configurable tick rate.** `TWIN_TICK_HZ` (default 10, matching the
previous hardcoded constant exactly) now drives both `telemetry_worker.py`
and `simulator.py` — previously two independent hardcoded `POLL_HZ = 10`
constants that would have silently diverged if only one had been made
configurable. Lower it in `.env` for constrained hardware. The roadmap's
planned 50Hz WebSocket-subscription upgrade should target this setting,
not introduce a third hardcoded value.

`.env.example` was also basically empty despite `settings.py` having
accumulated a full page of options across patches 10-14 — populated
properly now, matches the actual current settings.

---

## 8. PZEM-004T Power Monitoring

**Hardware:** PZEM-004T v3.0 energy monitor, wired via USB-serial (FTDI
adapter, Modbus RTU over RS485) directly to the Raspberry Pi. This is NOT
the ESP8266-HTTP-relay approach the old roadmap assumed — it's a direct
serial connection.

**Protocol:** Standard PZEM-004T Modbus RTU. Function code 0x04 (Read Input
Registers), 10 registers starting at 0x0000. CRC16 with Modbus polynomial
0xA001. Request frame: `01 04 00 00 00 0A 70 0D` (address 1).

**Register layout:**
- Reg 0: Voltage (× 0.1 V)
- Reg 1-2: Current (low/high × 0.001 A)
- Reg 3-4: Power (low/high × 0.1 W)
- Reg 5-6: Energy (low/high × 1 Wh)
- Reg 7: Frequency (× 0.1 Hz)
- Reg 8: Power Factor (× 0.01)
- Reg 9: Alarm status

**Configuration (`.env`):**
```
PZEM_SERIAL_PORT=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0
PZEM_SERIAL_BAUD=9600       # default
PZEM_MODBUS_ADDR=1          # default (factory default is 0xF8)
```
Leave `PZEM_SERIAL_PORT` empty to disable — the Power Delivery card shows
"Not connected" instead of misleading zeros.

**Error handling:** Follows `moonraker_client.py`'s pattern — never raises,
never blocks, logs errors rate-limited (once per 30s). Returns `None` values
when disconnected (not zeros) so the frontend distinguishes "not connected"
from "actually reading zero."

**Data flow:** `pzem_monitor.read()` is called each telemetry tick →
result is added to `self.latest["power"]` → flows through existing WebSocket
path → store.js `power` field → `DigitalTwinPage.jsx` Power Delivery card.

---

## 9. Authentication

**Design:** Single-tenant, zero-friction default. When `INDUS3D_PASSWORD` is
unset in `.env`, auth is disabled entirely — all routes behave exactly as
before. When set, every API route requires one of:
- Flask session cookie (created by `POST /api/auth/login`)
- `Authorization: Bearer <password>` header (for scripts/cURL/API clients)

**Configuration (`.env`):**
```
INDUS3D_PASSWORD=your_secret_password
```

**Routes:**
| Route | Method | Description |
|-------|--------|-------------|
| `/api/auth/login` | POST | `{"password": "..."}` → session cookie |
| `/api/auth/logout` | POST | Clears session |
| `/api/auth/status` | GET | `{"auth_required": bool, "authenticated": bool}` |

**Rate limiting:** 5 failed login attempts per IP per 5 minutes (in-memory
sliding window). Not persistent across restarts — acceptable for a
single-tenant 3D printer dashboard.

**Security details:**
- Password compared with `hmac.compare_digest` (timing-safe)
- Flask session secret auto-generated on first run, persisted to
  `backend/.flask_secret_key` (survives restarts)
- CORS updated: `supports_credentials=True` with origin reflection (required
  for session cookies in cross-origin dev mode)
- `window.fetch` patched globally with `credentials: 'include'` in main.jsx

**Frontend:**
- `LoginScreen.jsx` — full-screen login gate, themed for all 4 themes
- Settings modal gains a "Sign Out" button when auth is enabled
- `App.jsx` gates all telemetry/WebSocket init behind auth check —
  no API calls fire until authenticated (prevents 401 storms on mount)

**Allowlisted routes** (accessible without auth):
- `/api/auth/login`, `/api/auth/logout`, `/api/auth/status`
- `/api/health`
- OPTIONS requests (CORS preflight)

---

## 10. Disk Space Monitoring

Monitors free space on the partition that holds the Indus3D data directory.
Raspberry Pi SD cards fill up fast with timelapse frames, SQLite snapshots,
and G-code files.

**Module:** `services/disk_monitor.py`

**How it works:**
- Uses `shutil.disk_usage()` (stdlib, no dependencies)
- Polls every 60 seconds (configurable), not every telemetry tick
- Returns cached result between polls
- Sets `warn` and `critical` boolean flags based on configurable thresholds

**Configuration (`.env`):**
```
DISK_WARN_GB=2.0           # default: warn when < 2 GB free
DISK_CRITICAL_GB=0.5       # default: critical when < 0.5 GB free
DISK_CHECK_PATH=           # empty = backend directory partition
DISK_CHECK_INTERVAL_S=60   # how often to poll
```

**Data flow:** `disk_monitor.check()` is called each telemetry tick (returns
cached result until the polling interval expires) → added to
`self.latest["disk"]` → flows through WebSocket → store.js `disk` field →
`deriveAlerts()` generates `disk_warn` or `disk_critical` alerts.

**Alert behavior:** Disk alerts fire **regardless of print state** (same as
thermal runaway), because running out of disk space affects logging,
timelapses, and overall system health whether or not a print is active.

---

## 11. Database Migration System

Lightweight forward-only SQLite migration system for evolving the schema
without manual intervention.

**Module:** `db/migrator.py`

**How it works:**
1. A `schema_version` table tracks the current version number (single row)
2. On startup (after `init_db()`), scans `db/migrations/` for numbered
   Python files (e.g., `001_baseline.py`, `002_add_power_columns.py`)
3. Runs any migration whose number exceeds the current version, in order
4. Each migration file has a `def up(conn):` function that receives a
   sqlite3 connection
5. After all pending migrations succeed, the version is updated

**Creating a new migration:**
```bash
# Create a new file in db/migrations/ with the next number:
touch backend/db/migrations/003_add_some_column.py
```

```python
"""
Migration 003: Add some column
"""

def up(conn):
    conn.execute("ALTER TABLE some_table ADD COLUMN new_col TEXT")
    conn.commit()
```

**Design choices:**
- **No rollback** — for a single-user 3D printer dashboard, `down()` adds
  complexity without real value. Fix forward with a new migration.
- **Exits on failure** — running with a half-migrated schema is worse than
  not starting. Fix the migration and restart.
- **Filename-based discovery** — no registry file, just `NNN_name.py` files
  sorted by prefix. Simple, deterministic, git-friendly.
- **Runs after `init_db()`** — base tables are created by `init_db()`'s
  `CREATE TABLE IF NOT EXISTS`, then migrations handle schema evolution.

**Existing migrations:**
| # | File | Description |
|---|------|-------------|
| 1 | `001_baseline.py` | Marks the existing schema as version 1 (no changes) |
| 2 | `002_add_power_columns.py` | Adds power columns to `twin_snapshots` for PZEM recording |

## 12. Structured Logging

**What it does:**
- Centralizes all terminal output and application events into `backend/logs/indus3d.log`.
- Configures log rotation natively (max 5MB per file, keeps 3 backups) so disk space cannot be exhausted by logs.
- Preserves the same terminal output formatting (with emojis and colors) via `logging.StreamHandler(sys.stdout)` for local development visibility, while writing detailed timestamps, log levels, and module names to the file via `logging.handlers.RotatingFileHandler`.
- Suppresses chatty external libraries (e.g. `werkzeug` HTTP requests) to keep the logs focused on the system's own behavior.

**How it works:**
- Configured centrally in `backend/core/logger.py`.
- Invoked via standard `logging.info(...)` or `logging.error(...)` throughout the application.
- `print()` statements have been universally replaced to ensure standard output goes through the logging pipeline.

## 13. Safety-Critical Testing (`pytest`)

**What it is:**
A comprehensive test suite focusing primarily on components that interact with physical safety (power cutoff, thermal runaway) or alter print parameters mid-print (flow, speed). 

**What is tested:**
- **`test_thermal_model.py`**: Ensures runaway detection correctly triggers when temperature drops rapidly while PWM is high (>0.8). Validates that expected cooldowns (PWM = 0) do not trigger false alarms.
- **`test_quality_controller.py`**: Validates the mathematical thresholds for flow correction (M221) and speed reductions (M220), verifying that the deadband limits correctly suppress microscopic corrections.
- **`test_alert_actions.py`**: Tests the `execute_alert_action` framework to ensure critical alerts trigger immediate G-code (M112), informational alerts skip execution, and physical power cutoff triggers (if enabled) execute reliably.
- **`test_extrusion_model.py`**: Validates the logic behind distinguishing between `is_extruding` and rapid travel moves to prevent false under-extrusion flags.
- **`test_auth.py`**: Secures the API against brute-force attacks via sliding-window rate limiting logic.

**How to run:**
```bash
cd backend
.venv/bin/python -m pytest tests/
```

## 14. CI/CD & Deployments

- **CI Pipeline (`.github/workflows/ci.yml`)**: Automates linting (`flake8`), security auditing (`bandit`, `npm audit`), backend tests (`pytest`), and frontend bundle compilation on every PR/push.
- **Release Automation (`.github/workflows/release.yml`)**: Packaging Indus3D as a `indus3d-release.zip` file containing pre-built React static files and backend code whenever a `v*` tag is pushed.
- **Moonraker Update Manager**: Included `indus3d.cfg` allowing standard Kiauh/Moonraker integration.

## 15. Security & Rate Limiting

A tiered, sliding-window rate limiter protects the API (`backend/api/rate_limiter.py`):
- **Hardware Commands (`POST /api/v1/printer/*`)**: 10 requests / minute.
- **Login Attempts (`POST /api/v1/auth/login`)**: 5 requests / 5 minutes.
- **Default Telemetry**: 120 requests / minute.

If an IP violates limits 3 times in an hour, it receives a **24-hour ban** to prevent abuse. The frontend gracefully handles `429 Too Many Requests` responses via a patched `window.fetch` interceptor, displaying a "Connection Throttled" badge without crashing.

## 16. API Versioning & Swagger Docs

- **Versioning**: All routes strictly use the `/api/v1/` prefix (including WebSockets at `/api/v1/ws/twin`).
- **Auto-Documentation**: `flasgger` dynamically generates an interactive OpenAPI (Swagger) interface accessible at `http://<ip>:5001/api/docs/`.

---

## 4. Maintenance & Odometry Tracking

**What it measures:**
- The 10Hz `TelemetryWorker` tracks Euclidean motion across X, Y, and Z axes.
- Tracks edge-case transitions for `target > 50` on the extruder to increment heat cycles.
- Persists these metrics to `maintenance_counters` in SQLite every 5 seconds.

**Honest scope:**
- Does not track physical stress on belts (e.g. resonance load), only linear distance traveled.

---

## 5. Plugin System

**How it works:**
- Drop any `.py` script into `backend/plugins/`.
- If the script exports a `register_routes(app)` function, `server.py` invokes it on boot.
- This allows safely sandboxing API additions without merging them into core routing.

## TrueTwin Simulator Aliasing
When running the 3D Digital Twin in `--sim` mode, the time-compressed nature of the physics loop (teleporting 20 waypoints per 10Hz tick) causes massive aliasing if we attempt to draw a live trail between sampled positions. The live trail renderer is therefore safely suppressed in `simMode` to prevent it from drawing a jagged, garbage-like web across the pre-rendered high-resolution G-code toolpath.

## Mathematical Kinematic and Physical Models

**How it works:**
- `backend/digital_twin/control_models.py` isolates pure mathematical equations extracted from additive manufacturing research papers.
- The models include:
  - **Bead Geometry:** Calculates stadium-shaped bead cross-section and dynamic width from raw filament parameters to enhance Pressure Advance calculations via Nozzle Exit Velocity.
  - **Segment Kinematics:** Computes precise segment distance, time, and filament feed velocity based on physical Euclidean mapping.
  - **Thermal Lag & Coalescence:** Implements a first-order thermal lag predictor and Frenkel-Bellehumeur coalescence rate equation. Dynamically boosts temp or reduces fan speed if interlayer bonding drops below threshold.
  - **Zero-Jerk Motion (Sinusoidal):** Calculates a sinusoidal distance-to-speed scaling constraint to cap velocity on micro-segments.
  - **Closed-Loop PI Control:** Implements integral tracking error accumulators for temperature, and layer-to-layer closed-loop Z-offset correction.
- `quality_controller.py` executes these models every 5 seconds and issues optimized `SET_VELOCITY_LIMIT`, `SET_PRESSURE_ADVANCE`, `M104`, `M106`, and `SET_GCODE_OFFSET` commands.


## 17. Feature Ideas & Roadmap (Future)

Based on industry research across prosumer (Bambu Lab, Prusa) and industrial (Stratasys, Carbon, Formlabs) platforms, the following features are uniquely suited for Indus3D's architecture:

1. **Interactive "Skip Object" via 3D Digital Twin**
   - *Inspired by:* Bambu Lab / Prusa
   - *Concept:* Parse G-code object bounding boxes (`[exclude_object]`) and render them as clickable hitboxes in the 3D Digital Twin. Clicking a failed part instantly stops extruding for that specific object.

2. **Advanced Component Wear & Consumables Tracking**
   - *Inspired by:* Carbon / Formlabs
   - *Concept:* Expand the maintenance API to track specific consumable life cycles (e.g., Nozzle hours based on material abrasiveness, Carbon filter life based on ABS/ASA printing time, Belt travel distance).

3. **Virtual Spool Manager**
   - *Inspired by:* Formlabs (NFC) / Bambu Lab (RFID)
   - *Concept:* Register a spool's starting weight. Indus3D strictly subtracts extruded mass using `live_e` kinematics data, blocking prints if there is insufficient material remaining.

4. **Automated QA Job Reporting**
   - *Inspired by:* Stratasys / Carbon
   - *Concept:* Generate a PDF compliance report at the end of every print containing thermal variance graphs, speed telemetry, and a final webcam snapshot for quality assurance.

5. **Local AI Failure Detection**
   - *Concept:* A lightweight, locally hosted OpenCV/TensorFlow model watching the webcam stream to detect spaghetti or detachment, automatically pausing the print without cloud dependencies.

6. **Indus3D Local Touch UI (KlipperScreen Alternative)**
   - *Inspired by:* KlipperScreen's ubiquity but acknowledging its feature limitations.
   - *Concept:* Develop a custom, lightweight PySide6 or web-based touchscreen interface specifically for Indus3D. It would run locally on the Pi's connected screen, providing immediate access to the Digital Twin, AI failure detection states, and interactive Skip Object capabilities right at the printer, vastly outperforming the stock KlipperScreen experience.

## 18. Indus3D Lab Operations (QA, Vision, and Autonomous Throttling)
- **Computer Vision (YOLOv8):** `backend/edge/inspector.py` implements a real-time YOLOv8 object detector for Spaghetti, Warping, and Blob defects. This intercepts the camera feed and streams confidence alerts into the primary telemetry pipe.
- **Closed-Loop QA Verification:** The `QAReporter` (`backend/services/qa_reporter.py`) cross-references the actual print dimensions against an AS9100 standard CAD specification JSON to catch Out of Tolerance (OOT) parts automatically.
- **Jobs & Work Orders:** The system uses `backend/workers/job_queue.py` to allow the user to manage print jobs as trackable work orders, essential for multi-printer lab environments.
- **Config Versioning:** SQLite-backed version control tracks all changes to the machine configuration over time.
- **Autonomous Stress Mitigation:** The digital twin calculates continuous structural stress metrics. The `QualityController` ingests this `stress_score` and mathematically derives required drops in Square Corner Velocity (SCV) and Acceleration (`SET_VELOCITY_LIMIT`), pushing them to Klipper dynamically to mitigate machine wear.
