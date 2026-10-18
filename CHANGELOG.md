# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
