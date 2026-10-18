# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Extended `TelemetryWorker` with default offline state and multi-sensor concurrent monitoring.
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
