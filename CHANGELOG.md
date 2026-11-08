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
