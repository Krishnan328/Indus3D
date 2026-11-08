# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.0] - Intelligent Automation: KAMP, Sensor-Aware Pre-Flight, Git Backups & Visual QA Audit

### Added
- **KAMP (Klipper Adaptive Meshing & Purging) Suite (`kamp/`, `klipper/kamp/`)**:
  - `KAMP_Settings.cfg`: Configurable probe and purge parameters with Eddy rapid-scan bounds protection.
  - `Adaptive_Mesh.cfg`: Intercepts `BED_MESH_CALIBRATE` to dynamically restrict mesh probing to the exact bounding box of sliced objects. Automatically scales probe count based on footprint dimensions.
  - `Adaptive_Purge.cfg` (`LINE_PURGE`): Dynamically purges a clean strip immediately adjacent to the printed part, saving filament and cycle time.
  - `Smart_Park.cfg` (`SMART_PARK`): Parks toolhead 5mm above the print area near the first extrusion point during final nozzle heatup, avoiding ooze and bed travel drool.
- **Sensor-Aware Pre-Flight PRINT_START & PRINT_END (`print_start_end.cfg`)**:
  - `PRINT_START`: Parametric slicer integration (`BED_TEMP`, `EXTRUDER_TEMP`, `CHAMBER_MIN`, `SOAK_MINS`) with dual-stage pre-heating (150°C standby during probing), automatic wipe-brush cleaning (`NOZZLE_WIPE`), KAMP rapid-scan adaptive mesh, and smart priming.
  - `PRINT_END`: Automatic safe retraction, non-colliding Z-hop, rear toolhead parking, heater shutdown, fan cutoff, and mesh clearance.
- **Automated Git Configuration Backup (`services/config_backup.py`, `api/routes/printer.py`)**:
  - Real-time Git repository tracking for Klipper and Moonraker configuration directories.
  - Auto-backup on configuration save with file summaries and timestamps.
  - Complete REST API: `GET /api/printer/config/backups`, `POST /api/printer/config/backup`, `GET /api/printer/config/backup/diff`, and `POST /api/printer/config/backup/restore`.
  - Safety (review fixes): built lazily (no git at import) and **disabled** when no Klipper config dir exists (`KLIPPER_CONFIG_DIR`, `/var/lib/moonraker/config`, `~/printer_data/config`, `~/klipper_config`) - it never falls back to a folder in the source tree.
  - Secrets stay out of the history: files named like `*token*`, `*secret*`, `*password*`, `*credentials*`, `*telegram*`, `*.env` are never tracked, and files whose content has token/password/api_key/secret assignments, MQTT credentials, Discord webhooks or Telegram bot tokens are skipped and listed as `skipped_secrets`. `.json` files (Moonraker/Mainsail UI state) are opt-in with `INDUS3D_CONFIG_BACKUP_JSON=1`.
  - Manual backup and restore need `{"confirmed": true}`; restore also needs an idle printer (409 during a print), a hex commit hash that exists in the history (no `HEAD~3`/branch names), takes a "Pre-restore safety snapshot" first, never deletes files, and answers with `changed_files` / `needs_firmware_restart`.
  - The auto-backup after a config save is time-bounded (8 s) and never fails the save.
- **Object exclusion hardening**: `POST /api/v1/twin/exclude_object` only accepts a strict name that Klipper reports, requires an active print, checks the Klipper result (422/502 on refusal, no notification) and the UI rolls back its optimistic "cancelled" mark and shows the error.
- **Rich Outbound Webhook Notifications (`core/notifications.py`)**:
  - Discord embeds with thematic status colors (Blue/Green/Amber/Red) and Telegram HTML cards.
  - PZEM-004T live energy telemetry reporting (total Wh, estimated electricity cost, peak power).
  - High-resolution live camera snapshot attachments uploaded directly via multipart form-data on print completion, emergency halts, and defect exclusions.
- **Interactive 3D Exclude-Object & Objects Manager Drawer (`frontend/src/Viewport.jsx`)**:
  - Interactive 3D object bounding box selection with raycast hover feedback, dimensions, and click-to-cancel confirmation.
  - Floating "Objects (Active/Total)" HUD drawer providing instant list-based visibility and single-click cancellation of individual objects.
  - Synchronized with `store.js` optimistic state updates and backend `/api/v1/twin/exclude_object`.
- **Timelapse Integration with QA Reports & AS9100 Visual Audit (`core/timelapse.py`, `services/qa_reporter.py`)**:
  - Automated extraction of initial and final keyframe thumbnails for print traceability.
  - SHA-256 cryptographic video hashing recorded in `print_history` table (migration `013_add_timelapse_to_history.py`).
  - AS9100 Certificate of Conformance extended with immutable visual audit records and keyframe comparison page.

## [2.1.2] - Multi-Distribution Packaging: KIAUH Extension (Debian) & Pure NixOS Flake

### Added
- **Official KIAUH Extension (`integrations/kiauh/`)**:
  - Implemented `metadata.json` and `extension.py` compatible with the KIAUH v6 community extension architecture.
  - Added `install-extension.sh` one-line installer linking Indus3D into `~/kiauh/extensions/indus3d/` for interactive menu-driven installation, updates, and service management.
  - Added robust `indus3d_installer.sh` handling Debian/Raspberry Pi OS APT dependencies, virtualenv setup, Moonraker update manager injection, and Rust DSP compilation.
- **Unified Standalone Scripts (`install.sh`, `uninstall.sh`)**:
  - Streamlined root CLI installer to wrap `indus3d_installer.sh` with full dependency auditing and systemd service creation.
- **NixOS Declarative Packaging Documentation (`docs/DISTRIBUTION.md`)**:
  - Comprehensive comparison and setup guide detailing `flake.nix`, `nix/modules/indus3d.nix`, sandboxed systemd execution, and remote deployment.

## [2.1.1] - Hardware Decoupling, External Sensor Integration & Serial Protection

### Added
- **Smart Filament Sensor Integration (`services/filament_sensor.py`)**:
  - Live HTTP telemetry client on port 7126 reading measured filament diameter (AS5600 magnetic angle), feed velocity, volumetric flow, remaining spool weight, and clog/runout detection.
  - Dynamically updates the digital twin's `ExtrusionModel` cross-sectional bead area from actual measured filament diameter.
- **ESP8266 Multi-Sensor Bed & Chamber Hub (`services/bed_sensor.py`)**:
  - Live HTTP telemetry client on port 7127 streaming ADXL345 bed acceleration, jerk delta, and BME280 chamber environment (temperature, relative humidity, barometric pressure).
  - Chamber temperature dynamically injected into device temperatures and Mainsail parity dashboard cards.

### Fixed
- **Serial Port Hijacking & MCU Disconnection Prevention**:
  - Eliminated arbitrary `/dev/ttyACM*` fallback in `indus3d_sensor_daemon.py`, preventing the filament daemon from grabbing Klipper's toolhead MCU (EBB36) or probe MCU (BTT Eddy).
  - Explicitly filtered out any `/dev/serial/by-id/*Klipper*` serial devices from sensor auto-discovery.
  - Initialized `speed_mm_s` before telemetry packet parsing loop to eliminate `UnboundLocalError`.
- **ATmega2560 MCU Reset Lockup**:
  - Replaced `restart_method: command` with `restart_method: arduino` in Klipper `printer.cfg`, restoring hardware DTR/RTS resets when the mainboard enters a shutdown state.
- **ESP8266 Daemon Non-blocking Crash Reset**:
  - Replaced blocking `self.serial_lock` in `esp_bed_monitor_daemon.py` with timed acquisition (`timeout=0.25`), preventing HTTP handler deadlocks during `/reset_crash`.
- **Dashboard UI & Viewport Stability (Commit `2135ad3`)**:
  - Deployed updated frontend bundle featuring device temperature cards (BTT Eddy, BTT Eddy Mcu, EBB36, Chamber), optimistic target inputs, open thermistor sanitization (`--°C (Sensor Open)`), and eliminated spurious 3D origin trails.

## [2.1.0] - Auto Z-Offset & Tribo-Acoustic Bed Adhesion Optimization

### Added
- **Rust DSP Auto-Z Engine (`backend/dsp/`)**:
  - Implemented `AutoZMetrics` in `dsp.rs` tracking kinematic jerk, kurtosis surges, and the High-Frequency Friction Index (HFFI).
  - Hertzian contact detection for pre-print nozzle touch-down probing ($j_z > 400\text{ g/s}$ or kurtosis $> 6.0$).
  - Spectral energy ratio separating micro-asperity tribo-friction ($1200 - 1600\text{ Hz}$) from motor step harmonics ($20 - 400\text{ Hz}$).
  - High-performance binary IDX packet and CSV stream ingestion.
  - Standalone `--analyze-csv` CLI flag in `main.rs` for Klipper input-shaper CSV parsing.
- **Closed-Loop Quality Controller (`quality_controller.py`)**:
  - In-situ first layer bed adhesion optimization: autonomously baby-steps Klipper Z-offset via `SET_GCODE_OFFSET Z_ADJUST=... MOVE=1`.
  - Classifies print into `rubbing` (+0.025 mm relief trim), `under_squish` (-0.015 mm adhesion boost), and `optimal`.
  - Rate-limiting (2.0s cooldown) and safety clamping ($[-0.08, +0.08]\text{ mm}$) to guarantee physical safety.
- **Digital Twin & Telemetry Bridge (`dsp_bridge.py`, `vibration_monitor.py`)**:
  - Structured `auto_z` telemetry stream exposed over UDP 3201.
  - Live alerting for first-layer nozzle rubbing anomalies.
- **Frontend Visualization (`VibrationPanel.jsx`)**:
  - Real-time Bed Friction badge displaying live HFFI, print squish regime, and active Z-trim adjustments.
- **Mathematical Documentation**:
  - Updated `docs/VIBRATION_PIPELINE.md`, `extracted_equations.md`, and `README.md` with complete contact mechanics and Stefan squeeze-flow derivations.
## [Unreleased]

### Added
- Working plugin framework (`core/plugin_hooks.py`, `core/command_pipeline.py`, `plugins/`); see `docs/PLUGINS.md`. The loader is now actually called at startup.
- Plugins: `shadow_mode` (records the G-code the controller would send while the auto-pilot is off), `audit_trail` (persists every command, veto and correction reason to `command_log`/`action_log`), `arbiter` (prevents M221/M220 fights with other writers), `watchdog` (disables the auto-pilot on runaway behaviour), `approval` (optional human approval of corrections), `first_layer_guard`, `thermal_sanity`, `filament_sensor` (sensor daemon bridge), `health_score`, `prometheus_exporter` (`/metrics`).
- Analysis, integration and data plugins: `run_recorder`, `corrective_tracker`, `corrections_timeline`, `model_scorer`, `controller_tuner`, `slicer_feedback`, `print_report`, `calibration_runner`, `spool_planner`, `maintenance_advisor`, `energy_cost`, `fleet_aggregator`, `esp_bed_hub`, `chamber_environment`, `tmc_current`, `chat_actions`, `mqtt_bridge`, `webhook_events`, `spoolman_sync`, `usb_link_health`. New `controller.inputs` hook.
- Filament sensor integration: dashboard card, measured flow/diameter as controller inputs (flow replacement opt-in), measured grams written back to print history and the virtual spool, audit entries for sensor faults/runout/auto-flow, authenticated calibration actions, `helpers/filament_sensor/install_sensor.py` (idempotent installer, templated systemd unit) and an optional KIAUH step. The daemon now binds to 127.0.0.1 and requires an `X-Indus3D-Action` header for its state-changing endpoints.
- ESP8266 bed sensor hub integration (`helpers/filament_sensor/esp8266_sensor_hub`, firmware 1.1.0): a host daemon that owns the USB serial port (reconnects, never resets the ESP, pauses the print through Moonraker and runs `BED_CRASH_HANDLER JERK=<mg>` on a crash, HTTP API on 127.0.0.1:7127, optional MQTT feed for a Moonraker `[sensor]`); `esp_hub_ctl.py`; a serial command protocol (`PING`, `STATUS`, `SET_CRASH_THRESHOLD`, `RESET_CRASH`, `START_SHAPER`, `STOP_SHAPER`) with a baud switch for 1600 Hz captures; production Klipper macros (`BED_CRASH_HANDLER`, `BED_CRASH_RESUME`, `BED_SHAPER_CALIBRATE_Y`, `SET_BED_CRASH_THRESHOLD`, status/reset buttons) with `gcode_shell_command` entries; `install_hub.py` (udev rule keyed on serial number or USB port, systemd unit, Klipper/Moonraker includes); input shaper analysis with textbook ZV/MZV/ZVD/EI/2HUMP_EI/3HUMP_EI shapers, damping estimate, smoothing-based maximum acceleration and a safe `printer.cfg` updater.
- `esp_bed_hub` plugin rewrite: telemetry stored in `telemetry_samples`, stale-data detection, crash audit, command hold while latched, opt-in `EXCLUDE_OBJECT`, reset/threshold actions, `/metrics`, `/api/v1/environment` fed from the BME280, and a "Bed Sensor Hub" dashboard card.
- Control foundations for the Mainsail/Fluidd feature gap (phase 0): `POST /api/v1/printer/macro/<name>` (macro name must be one of Klipper's own `gcode_macro` objects, parameters strictly validated, confirmation while printing except PAUSE/RESUME/CLEAR_PAUSE); `GET /api/v1/printer/status` (cached Klipper object status for heaters, temperature sensors, fans, output pins and leveling helpers, plus a capabilities summary and the configured heater limits); `api/moonraker_util.py` helpers; a `ui_adjust` rate-limit category for interactive controls; `arbiter.manual_override()` / `note_manual_change()` so a manual change makes the controller yield that family; frontend store slices (`slices/`), a debounce helper and `npm test` (node's built-in runner).
- System page (nav rail → System): host (OS, CPU, memory, temperature, throttling), MCUs, systemd services (restart/start/stop), software updates (per component and all, progress, recover), Moonraker database backups (create/restore/delete), devices (USB, serial with the recommended `by-id` path and a copy button, CAN on request, video, `usb_link_health` suspects) and an alert banner list. Backend `api/routes/system.py` (`/api/v1/system/*`, thin validated Moonraker proxies: confirmation flags, refused during a print, one update at a time, never stops Indus3D's own service without `confirm_self`, 502 when Moonraker is down, 404 `unsupported` when this Moonraker lacks an endpoint, simulator stand-in data) and the `host_alerts` plugin (edge-triggered notifications for under-voltage, pending updates, outdated Moonraker, announcements, failed components; `INDUS3D_HOST_ALERTS=0` disables). State-changing system calls (POST and DELETE) use the strict `hardware_cmd` rate limit. See `docs/SYSTEM_PAGE.md`.
- Toolhead and thermals (track-toolhead): typed control endpoints `POST /api/v1/printer/adjust/{heater,fan,output_pin,speed,flow,pressure_advance,retraction,babystep,save_z_offset,motors_off,level,extrude}` (`api/routes/adjust.py`). The browser sends numbers and Klipper object names only; the server validates them (finite, bounded, never bool; names must exist in Klipper), builds the G-code, refuses motion/leveling/extrusion during a print, checks `can_extrude`, `firmware_retraction` and leveling capabilities, bounds heater targets to the configured `max_temp` minus 5 °C, requires `confirmed: true` for saving the Z offset (and says SAVE_CONFIG is needed), answers 502 when Moonraker is down, has a simulator branch, and tells the arbiter (`note_manual_change`) so the quality controller yields flow, speed, pa, nozzle_temp, bed_temp, fan, z_offset and retraction after a manual change. Toolhead card with Move (bars / cross / circle), Extruder (amount and speed presets, load/unload/clean/park macros), Heat (setpoints, fans, output pins), Tune (speed, flow, pressure advance, firmware retraction), Z offset (configurable babystep increments, save to probe/endstop) and Level (only what the printer has, manual-probe TESTZ/ACCEPT/ABORT, motors off) tabs; options in Settings -> Control.
- Temperature chart rebuilt on uPlot (loaded lazily, own 55 kB chunk): every heater with its target, temperature sensors and fans from Klipper's status, optional heater-power and fan-speed overlays, per-series show/hide, hover highlight, drag-to-zoom, smoothing (None/1/3/5/10/15/30 s), per-series colours (saved in `uiPrefs` and mirrored to the server preferences), 1 min live and 1 h / 6 h / 24 h ranges. `GET /api/v1/printer/thermal_history?minutes=` backfills from Moonraker's temperature store and from SQLite (`twin_snapshots` for extruder/bed, `telemetry_samples` for the ESP8266 hub's chamber temperature and humidity; the hub stands in for the chamber when Klipper has no chamber sensor). `GET /api/v1/printer/sensors` proxies Moonraker's sensors (the MQTT `bed_hub` sensor, falling back to the `esp_bed_hub` plugin) into a new collapsible Sensors dashboard card with sparklines.
- Vetoed commands are now fed back to the controller (`notify_vetoed`) so they are proposed again instead of lost.
- Files, print queue and editor (track-files): typed file API `/api/v1/files/*` (`api/routes/files.py`): roots (whitelist plus custom roots Moonraker lists; read-only roots stay read-only), directory listing with slicer metadata and disk usage, flat tree for the finder, streamed download (Range, inert types only), text read/write with modified-time conflict check and `config_history` audit, mkdir, rename, move, copy, delete, ZIP (temporary archive removed afterwards), streamed upload with a size limit, batched thumbnails and metadata refresh. Paths are validated (no `..`, absolute paths, backslashes, NUL/control characters); non-empty folders need `confirmed: true`; replacing existing files needs `overwrite`; the file being printed (and folders containing it) can not be deleted, renamed, moved or overwritten and nothing in `config` can be changed during a print; 502 when Moonraker is down, 501 `unsupported` when an endpoint is missing; the simulator is served from an in-memory tree. Print queue `/api/v1/queue/*` (`api/routes/queue.py`) on Moonraker's `[job_queue]`: status with per-job metadata, totals and an ETA that counts the running print, add (several files, "multiply" copies, front/end), remove, pause, start, jump, and reorder (Moonraker only has jump-to-front, so other orders re-add the changed tail first and remove the old entries after, never losing a job); a missing `[job_queue]` returns the snippet to add; starting stays manual and the UI says so. New file manager UI (root tabs, breadcrumbs, sortable metadata columns, multi-select, context menu, copy/cut/paste, drag and drop between folders and from the desktop with upload progress, live filter, Ctrl+P go-to-file, filters for hidden/backup/temp/rolled-log/printed files, image/video/Markdown/text preview, toolpath preview with a large-file confirmation, thumbnails with adjustable size, disk-usage warning), a queue tab and a dashboard Queue card, and a lazily loaded CodeMirror 6 editor (own Klipper config, Moonraker `.conf`, G-code and Jinja highlighting, outline, folding, search, Ctrl+S, save and restart, unsaved-changes warning, theme matching, shortcut help, JSON/Markdown modes, read-only mode), reusable from the file manager and the configuration editor.
- `helpers/` folder: filament sensor, lab toolkit, corrective G-code tracker, KIAUH extension.

### Fixed
- Back-to-back queued jobs were treated as one print: Moonraker loads the next job faster than the telemetry poll, so the "complete" state was never seen and the run recorder, spool planner, controller state, timelapse and print history never saw an end/start. `core/job_tracker.py` now recognises a hand-over (different file, or `print_duration` restarting for the same file), the telemetry worker books the old job, resets the controller and shows plugins a "complete" tick before the new job starts, and the run recorder and spool planner also split runs on their own. The state snapshot now carries `print_duration`.
- The configuration editor in `Modals.jsx` loaded `/api/v1/printer/files/config…`, routes that no longer exist, so it could not list or open files; it now uses `/api/v1/printer/config/list` and `/config/<name>`.
- Dashboard macro buttons were refused (HTTP 403) in live mode because user macros are not on the G-code allowlist; they now use the typed macro endpoint.
- The interactive controls shared the 10-requests-per-minute limit of restart/shutdown, so a few jog clicks produced HTTP 429 and repeated clicks could ban the IP for 24 h. Jog, execute, macros and the console now have their own 120/min limit that never bans.
- Settings -> Control (and every other Settings toggle) did nothing on a fresh browser: `store.js` never defined `setUiPref` and `uiPrefs` had no defaults, so the tab crashed on `uiPrefs.moveDistances.join`. Added `slices/uiPrefsSlice.js` with defaults for every key the app reads and a persisting `setUiPref`.
- Jogging the extruder with `M82` active would have moved it to an absolute position; jogs now force relative extrusion and restore the printer's modal state.
- ESP8266 hub: the host monitor could reset the board on every connect (DTR/RTS) and showed stale data as live; shaper capture failed at 115200 baud (1600 Hz needs ~240 kbit/s); the crash alert did not carry the measured jerk; the analyzer's EI/hump shapers and acceleration limit were not the published definitions; the wiring document listed pins that do not match the verified hardware; the sample Moonraker config contained a second `[authorization]` section that would stop Moonraker from starting.
- Rust DSP sources restored after an accidental revert (binary stream, collision events, notch filter, resonance analyser).
- `printer.py`: config save crash, `/macros` NameError, G-code allowlist bypass via newlines, homing during a print.
- Quality controller: flow-loop gain and curve-factor compounding, clog detection now only runs on a real current measurement; sintering and roughness model errors.

## [2.0.0] - Production Release

### Added
- Complete architecture documentation and system flowcharts in `README.md`.
- Community contribution guidelines (`CONTRIBUTING.md`), Code of Conduct (`CODE_OF_CONDUCT.md`), and Security Policy (`SECURITY.md`).
- Project development roadmap (`docs/ROADMAP.md`).
- GitHub issue and pull request templates (`.github/`).
- Formal MIT License.
- Direct production SPA hosting from Flask backend (`/frontend/dist`), eliminating Node.js background memory footprint on Klipper hosts.
- Hardened automated installer (`install.sh`) supporting Debian / Raspberry Pi OS with auto-venv, system packages, and frontend compilation.
- Moonraker update manager integration via `[update_manager indus3d]` in `moonraker.conf`.
- Klipper safety macros in `indus3d.cfg` and ADXL345 accelerometer streaming module in `klipper_modules/indus_vibration.py`.
- Automated systemd service unit (`indus3d.service`) with non-root user permissions and auto-restart policies.
- Clean uninstallation script (`uninstall.sh`) with safe configuration restoration.
- Unit test suite expansion to 32 tests covering static frontend serving and API route guards.

## [2.0.0-phase7] - React 18 Modular Frontend, Bento Dashboard & Touch UI

### Added
- Modular Bento dashboard grid in `frontend/src/DashboardGrid.jsx`.
- Dedicated 7-inch Raspberry Pi Klipper touchscreen interface (`frontend/src/TouchUI.jsx`).
- Interactive Three.js 3D viewport with STL build plate rendering (`frontend/src/Viewport.jsx`, `frontend/src/PrintBed.jsx`).
- WebGL multi-layer G-code path visualizer (`frontend/src/GCodeVisualizerV2.jsx`).
- Drag-and-drop OrcaSlicer bed profile import modal (`frontend/src/BedSettingsModal.jsx`).
- Calibration and resonance tuner panels (`frontend/src/CalibrationWizard.jsx`, `frontend/src/ShaperTuner.jsx`).
- Electrical power monitor card (`frontend/src/PowerPanel.jsx`) and Spoolman picker (`frontend/src/SpoolPicker.jsx`).
- Multi-camera video feed monitor (`frontend/src/CameraFeeds.jsx`) and timelapse gallery (`frontend/src/TimelapseGallery.jsx`).
- Auto-reconnecting Zustand store with optimistic updates in `frontend/src/store.js`.
- Theme system (`frontend/src/theme.js`) supporting dark mode and brutalist UI.

### Removed
- Legacy monolithic `GCodeVisualizer.jsx`.

## [2.0.0-phase6] - Bed Adaptation, OrcaSlicer Profile Import & REST API Architecture

### Added
- Bed Safety and Adaptation API in `backend/api/routes/bed.py`.
- Slicer profile importer for OrcaSlicer and PrusaSlicer `.json` configurations.
- Custom bed STL model upload and bounding geometry extraction.
- Hardware exclusion zones preventing collisions with bed screws, clips, and purge buckets.
- Unified REST API routing in `backend/api/routes/` (`printer.py`, `spools.py`, `edge.py`, `profile.py`, `sim.py`, `twin.py`).
- Modernized API server (`backend/api/server.py`) with WebSocket broadcasting and CORS support.
- Multi-threaded runtime coordinator in `backend/main.py`.
- Unit test suite for bed safety and profile parsing in `backend/tests/test_bed_safety.py`.

### Removed
- Deprecated legacy routes `backend/api/routes/control.py` and `backend/api/routes/telemetry.py`.

## [2.0.0-phase5] - Physics Digital Twin Models & Closed-Loop Autopilot

### Added
- Analytical kinematic, thermal, extrusion, stepper dynamics, and acoustic models in `backend/digital_twin/control_models.py` & `control_models_extra.py`.
- Material rheology and thermal profiles for PLA, PETG, ABS, and TPU in `backend/digital_twin/filament_profiles.py`.
- Closed-loop Autopilot Quality Controller in `backend/digital_twin/quality_controller.py` with anti-windup clamping.
- Post-print QA audit reporter in `backend/services/qa_reporter.py`.
- Real-time G-code layer annotation service in `backend/services/gcode_annotator.py`.
- Upgraded Digital Twin simulator in `backend/workers/simulator.py` with dynamic waypoints and baked 3DBenchy contours.
- Edge inspection and watchdog monitor in `backend/edge/`.
- Unit test suites for extrusion, thermal runaway, and quality controller logic.

## [2.0.0-phase4] - Rust Accelerometer DSP Pipeline & Input Shaper Tuner

### Added
- Ultra-low-latency Rust accelerometer DSP pipeline crate in `backend/dsp/`.
- UDP telemetry bridge (`backend/workers/dsp_bridge.py`) with `SO_REUSEADDR` socket management.
- Mechanical vibration harmonic monitor in `backend/digital_twin/vibration_monitor.py`.
- Input Shaper resonance tuner and peak detection algorithm in `backend/core/shaper_tuner.py`.

## [2.0.0-phase3] - Sensor Telemetry, Power (PZEM), Spoolman & Alert Webhooks

### Added
- PZEM-004T AC energy and electrical power monitoring service (`backend/services/pzem_monitor.py`).
- Spoolman active filament spool tracking client (`backend/services/spoolman_client.py`).
- Storage space and flash wear monitor (`backend/services/disk_monitor.py`).
- Hardware status LED controller with configurable RGB color profiles (`backend/services/led_controller.py`).
- Layer-change print timelapse capture daemon (`backend/core/timelapse.py`).
- Multi-channel notification webhook dispatchers for Discord, Telegram, and Pushover (`backend/core/notifications.py`).
- Configurable alert action execution and deduplication engine (`backend/core/alert_actions.py`).
- Extended `TelemetryWorker` polling Klipper, power, and environmental sensors concurrently.
- Unit tests for alert dispatch and deduplication in `backend/tests/test_alert_actions.py`.

## [2.0.0-phase2] - Session Authentication & Sliding-Window Rate Limiting

### Added
- Session-based token authentication middleware in `backend/api/auth.py`.
- Sliding-window rate limiter in `backend/api/rate_limiter.py` with tiered protection:
  - Brute-force protection on `/api/v1/auth/login`.
  - Motion and hardware G-code execution throttling.
  - Automatic temporary IP bans for repeated offenders.
- Unit test suite for security and rate limiting in `backend/tests/test_auth.py`.

## [2.0.0-phase1] - Repository Foundation, Unified Settings & DB Migrations

### Added
- Production `.gitignore` ignoring virtual environments, build artifacts, node_modules, and SQLite databases.
- Centralized configuration system in `backend/config/settings.py`.
- Versioned SQLite database migration framework in `backend/db/migrator.py` with migrations `001` through `009`.
- Flight logging and telemetry database models in `backend/db/models.py`.
- Rotating file logging handler (`backend/core/logger.py`) and worker lifecycle coordinator (`backend/workers/manager.py`).
- Automated installation scripts: `install.sh`, `uninstall.sh`, and `deploy_to_pi.sh`.
- Klipper configuration overrides template: `indus3d.cfg`.
- Pytest test runner configuration (`backend/pytest.ini`) and test fixtures (`backend/tests/conftest.py`).
- Developer guide in `docs/DEVELOPMENT.md`.

### Removed
- Legacy command queue subsystem (`backend/cmd_queue/`).
- Deprecated background queue worker (`backend/workers/queue_worker.py`).
